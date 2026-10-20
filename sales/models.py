import uuid

from django.db import models, transaction
from django.contrib.auth.models import User
from medications.models import Medication
from django.utils import timezone
from decimal import Decimal, ROUND_HALF_UP

CENT = Decimal("0.01")


def to_cents(value):
    """Arrondit un montant au centime (arrondi commercial)."""
    return Decimal(value).quantize(CENT, rounding=ROUND_HALF_UP)


class Customer(models.Model):
    """Modèle pour les clients"""
    
    CUSTOMER_TYPES = [
        ('particulier', 'Particulier'),
        ('entreprise', 'Entreprise'),
        ('assurance', 'Assurance'),
    ]
    
    # Informations de base
    first_name = models.CharField(max_length=100, verbose_name="Prénom")
    last_name = models.CharField(max_length=100, verbose_name="Nom")
    phone = models.CharField(max_length=20, verbose_name="Téléphone")
    email = models.EmailField(blank=True, null=True, verbose_name="Email")
    address = models.TextField(blank=True, null=True, verbose_name="Adresse")
    
    # Informations complémentaires
    date_of_birth = models.DateField(blank=True, null=True, verbose_name="Date de naissance")
    customer_type = models.CharField(max_length=20, choices=CUSTOMER_TYPES, default='particulier', verbose_name="Type de client")
    medical_conditions = models.TextField(blank=True, null=True, verbose_name="Conditions médicales", help_text="Allergies, maladies chroniques comme l'asthme, etc.")
    
    # Programme de fidélité
    loyalty_points = models.IntegerField(default=0, verbose_name="Points de fidélité")
    
    # Crédit
    credit_limit = models.DecimalField(max_digits=10, decimal_places=2, default=0, verbose_name="Limite de crédit")
    current_credit = models.DecimalField(max_digits=10, decimal_places=2, default=0, verbose_name="Crédit actuel")
    
    # Métadonnées
    created_at = models.DateTimeField(auto_now_add=True, verbose_name="Créé le")
    updated_at = models.DateTimeField(auto_now=True, verbose_name="Modifié le")
    
    class Meta:
        verbose_name = "Client"
        verbose_name_plural = "Clients"
        ordering = ['-created_at']
        permissions = [
            ("view_sensitive_customer", "Voir les données médicales et la date de naissance des clients"),
        ]
    
    def __str__(self):
        return f"{self.first_name} {self.last_name}"
    
    @property
    def full_name(self):
        return f"{self.first_name} {self.last_name}"
    
    @property
    def available_credit(self):
        """Crédit disponible"""
        return self.credit_limit - self.current_credit


class Sale(models.Model):
    """Modèle pour les ventes"""
    
    PAYMENT_METHODS = [
        ('especes', 'Espèces'),
        ('carte', 'Carte bancaire'),
        ('mobile_money', 'Mobile Money'),
        ('credit', 'Crédit'),
    ]
    
    STATUS_CHOICES = [
        ('en_cours', 'En cours'),
        ('completee', 'Complétée'),
        ('annulee', 'Annulée'),
    ]
    
    # Informations de base
    sale_number = models.CharField(max_length=50, unique=True, verbose_name="Numéro de vente")
    customer = models.ForeignKey(Customer, on_delete=models.SET_NULL, null=True, blank=True, related_name='sales', verbose_name="Client")
    
    # Montants
    subtotal = models.DecimalField(max_digits=10, decimal_places=2, default=0, verbose_name="Sous-total")
    discount_percentage = models.DecimalField(max_digits=5, decimal_places=2, default=0, verbose_name="Remise (%)")
    discount_amount = models.DecimalField(max_digits=10, decimal_places=2, default=0, verbose_name="Montant remise")
    total = models.DecimalField(max_digits=10, decimal_places=2, default=0, verbose_name="Total")
    
    # Paiement
    payment_method = models.CharField(max_length=20, choices=PAYMENT_METHODS, verbose_name="Mode de paiement")
    amount_paid = models.DecimalField(max_digits=10, decimal_places=2, default=0, verbose_name="Montant payé")
    change_amount = models.DecimalField(max_digits=10, decimal_places=2, default=0, verbose_name="Monnaie rendue")
    
    # Statut
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='en_cours', verbose_name="Statut") 
    
    # Métadonnées
    created_at = models.DateTimeField(auto_now_add=True, verbose_name="Date de vente")
    created_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, verbose_name="Vendu par")
    notes = models.TextField(blank=True, null=True, verbose_name="Notes")
    
    class Meta:
        verbose_name = "Vente"
        verbose_name_plural = "Ventes"
        ordering = ['-created_at']
    
    def __str__(self):
        return f"Vente #{self.sale_number}"
    
    def save(self, *args, **kwargs):
        # Calculer les montants (Decimal, arrondis au centime)
        self.subtotal = to_cents(self.subtotal)
        self.discount_amount = to_cents(Decimal(self.subtotal) * Decimal(self.discount_percentage) / 100)
        self.total = self.subtotal - self.discount_amount
        
        # Monnaie rendue : seulement si le client a donné plus que le total
        # (jamais pour une vente à crédit).
        paid = to_cents(self.amount_paid)
        self.change_amount = max(Decimal("0"), paid - self.total) if self.payment_method != 'credit' else Decimal("0")

        if self.sale_number:
            super().save(*args, **kwargs)
            return

        # Numéro de vente dérivé de l'identifiant : unique même si deux ventes
        # sont enregistrées au même instant ou si une vente est supprimée.
        # Un numéro provisoire unique occupe la colonne le temps d'obtenir l'id.
        self.sale_number = f"TMP-{uuid.uuid4().hex}"
        with transaction.atomic():
            super().save(*args, **kwargs)
            day = timezone.localtime(self.created_at).strftime('%Y%m%d')
            self.sale_number = f"V{day}-{self.pk:06d}"
            Sale.objects.filter(pk=self.pk).update(sale_number=self.sale_number)
    
    @property
    def profit(self):
        """Bénéfice : total encaissé moins le coût d'achat figé au moment de la vente."""
        total_cost = sum(item.unit_cost * item.quantity for item in self.items.all())
        return self.total - total_cost


class SaleItem(models.Model):
    """Lignes d'une vente"""
    
    sale = models.ForeignKey(Sale, on_delete=models.CASCADE, related_name='items', verbose_name="Vente")
    medication = models.ForeignKey(Medication, on_delete=models.PROTECT, verbose_name="Médicament")
    quantity = models.IntegerField(verbose_name="Quantité")
    unit_price = models.DecimalField(max_digits=10, decimal_places=2, verbose_name="Prix unitaire")
    # Prix d'achat au moment de la vente : le bénéfice d'une vente passée ne
    # change pas si le prix d'achat du médicament évolue ensuite.
    unit_cost = models.DecimalField(max_digits=10, decimal_places=2, verbose_name="Coût d'achat unitaire")
    subtotal = models.DecimalField(max_digits=10, decimal_places=2, verbose_name="Sous-total")
    
    class Meta:
        verbose_name = "Ligne de vente"
        verbose_name_plural = "Lignes de vente"
    
    def __str__(self):
        return f"{self.medication.name} x{self.quantity}"
    
    def save(self, *args, **kwargs):
        # Calculer le sous-total
        self.subtotal = to_cents(Decimal(self.unit_price) * self.quantity)
        
        super().save(*args, **kwargs)


class Prescription(models.Model):
    """Modèle pour les ordonnances"""
    
    customer = models.ForeignKey(Customer, on_delete=models.CASCADE, related_name='prescriptions', verbose_name="Client")
    sale = models.OneToOneField(Sale, on_delete=models.SET_NULL, null=True, blank=True, related_name='prescription', verbose_name="Vente associée")
    
    doctor_name = models.CharField(max_length=200, verbose_name="Nom du médecin")
    prescription_date = models.DateField(verbose_name="Date de prescription")
    prescription_image = models.ImageField(upload_to='prescriptions/', blank=True, null=True, verbose_name="Image de l'ordonnance")
    notes = models.TextField(blank=True, null=True, verbose_name="Notes")
    
    created_at = models.DateTimeField(auto_now_add=True, verbose_name="Créé le")
    
    class Meta:
        verbose_name = "Ordonnance"
        verbose_name_plural = "Ordonnances"
        ordering = ['-created_at']
    
    def __str__(self):
        return f"Ordonnance - {self.customer.full_name} ({self.prescription_date})"