"""
Logique métier d'une vente, indépendante de la vue HTTP.

Règle d'or : le navigateur n'envoie que des intentions (quels médicaments,
combien, quel mode de paiement). Tous les montants sont recalculés ici à
partir des prix enregistrés en base, en Decimal.
"""
from datetime import date
from decimal import Decimal, InvalidOperation

from django.db import transaction
from django.utils import timezone

from medications.models import Medication
from .models import Customer, Prescription, Sale, SaleItem

# Remise maximale autorisée à la caisse, en pourcentage.
MAX_DISCOUNT = Decimal("20")

PAYMENT_METHODS = {code for code, _ in Sale.PAYMENT_METHODS}


class SaleError(Exception):
    """Erreur métier dont le message peut être montré tel quel au vendeur."""


def _to_positive_int(value):
    # bool est une sous-classe d'int : True ne doit pas valoir « 1 boîte ».
    if isinstance(value, bool):
        raise SaleError("Quantité invalide dans le panier.")
    if isinstance(value, int):
        number = value
    elif isinstance(value, str) and value.strip().isdigit():
        number = int(value)
    else:
        raise SaleError("Quantité invalide dans le panier.")
    if number <= 0:
        raise SaleError("Quantité invalide dans le panier.")
    return number


def _to_decimal(value, field_label):
    if isinstance(value, bool) or value is None or value == "":
        raise SaleError(f"{field_label} invalide.")
    try:
        number = Decimal(str(value))
    except InvalidOperation:
        raise SaleError(f"{field_label} invalide.")
    if not number.is_finite():
        raise SaleError(f"{field_label} invalide.")
    return number


def _parse_items(items_data):
    """Regroupe les quantités par médicament : {medication_id: quantité totale}."""
    if not isinstance(items_data, list) or not items_data:
        raise SaleError("Le panier est vide.")
    quantities = {}
    for item in items_data:
        if not isinstance(item, dict):
            raise SaleError("Panier invalide.")
        try:
            med_id = int(item.get("medication_id"))
        except (TypeError, ValueError):
            raise SaleError("Un médicament du panier est introuvable.")
        quantities[med_id] = quantities.get(med_id, 0) + _to_positive_int(item.get("quantity"))
    return quantities


def _parse_prescription(raw):
    """Valide les informations d'ordonnance saisies à la caisse."""
    if not isinstance(raw, dict):
        raise SaleError("Ordonnance requise : saisissez le médecin et la date de prescription.")
    doctor_name = str(raw.get("doctor_name") or "").strip()
    if not doctor_name:
        raise SaleError("Ordonnance incomplète : le nom du médecin est obligatoire.")
    if len(doctor_name) > Prescription._meta.get_field("doctor_name").max_length:
        raise SaleError("Ordonnance invalide : nom du médecin trop long.")
    try:
        prescription_date = date.fromisoformat(str(raw.get("prescription_date") or ""))
    except ValueError:
        raise SaleError("Ordonnance incomplète : la date de prescription est invalide.")
    if prescription_date > timezone.localdate():
        raise SaleError("Ordonnance invalide : la date de prescription est dans le futur.")
    return doctor_name, prescription_date


def create_sale(user, data):
    """
    Crée une vente complète à partir des données de la caisse.

    Lève SaleError pour toute donnée refusée ; rien n'est écrit dans ce cas.
    """
    if not isinstance(data, dict):
        raise SaleError("Requête invalide.")

    quantities = _parse_items(data.get("items"))

    discount = _to_decimal(data.get("discount_percentage", 0) or 0, "Remise")
    if not Decimal("0") <= discount <= MAX_DISCOUNT:
        raise SaleError(f"La remise doit être comprise entre 0 et {MAX_DISCOUNT} %.")

    payment_method = data.get("payment_method")
    if payment_method not in PAYMENT_METHODS:
        raise SaleError("Mode de paiement invalide.")

    amount_paid = _to_decimal(data.get("amount_paid", 0) or 0, "Montant payé")
    if amount_paid < 0:
        raise SaleError("Montant payé invalide.")

    customer = None
    customer_id = data.get("customer_id")
    if customer_id:
        try:
            customer = Customer.objects.get(pk=int(customer_id))
        except (TypeError, ValueError, Customer.DoesNotExist):
            raise SaleError("Client introuvable.")

    with transaction.atomic():
        # Verrouille les médicaments (ordre stable pour éviter les interblocages)
        # et vérifie le stock avant toute écriture.
        medications = {
            med.id: med
            for med in Medication.objects.select_for_update().filter(id__in=quantities).order_by("id")
        }
        if len(medications) != len(quantities):
            raise SaleError("Un médicament du panier est introuvable.")
        today = timezone.localdate()
        for med_id, quantity in quantities.items():
            med = medications[med_id]
            if med.expiry_date < today:
                raise SaleError(f'"{med.name}" est périmé et ne peut pas être vendu.')
            if quantity > med.quantity:
                raise SaleError(
                    f'Stock insuffisant pour "{med.name}" '
                    f"(disponible : {med.quantity}, demandé : {quantity})."
                )

        # Médicament sur ordonnance : client identifié + ordonnance liée à la vente.
        prescription_meds = [med.name for med in medications.values() if med.requires_prescription]
        prescription_info = None
        if prescription_meds:
            names = ", ".join(sorted(prescription_meds))
            if customer is None:
                raise SaleError(f"Ordonnance requise pour {names} : sélectionnez le client.")
            prescription_info = _parse_prescription(data.get("prescription"))

        subtotal = sum(
            (medications[med_id].selling_price * quantity for med_id, quantity in quantities.items()),
            Decimal("0"),
        )

        sale = Sale(
            customer=customer,
            subtotal=subtotal,
            discount_percentage=discount,
            payment_method=payment_method,
            amount_paid=amount_paid,
            created_by=user,
            status="completee",
        )
        sale.save()

        for med_id, quantity in quantities.items():
            med = medications[med_id]
            SaleItem.objects.create(
                sale=sale,
                medication=med,
                quantity=quantity,
                unit_price=med.selling_price,
            )

        if prescription_info:
            doctor_name, prescription_date = prescription_info
            Prescription.objects.create(
                customer=customer,
                sale=sale,
                doctor_name=doctor_name,
                prescription_date=prescription_date,
            )

    return sale
