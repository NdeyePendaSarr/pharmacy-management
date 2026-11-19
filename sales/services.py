"""
Logique métier d'une vente, indépendante de la vue HTTP.

Règle d'or : le navigateur n'envoie que des intentions (quels médicaments,
combien, quel mode de paiement). Tous les montants sont recalculés ici à
partir des prix enregistrés en base, en Decimal.
"""
import calendar
import uuid
from datetime import date
from decimal import Decimal, InvalidOperation

from django.db import IntegrityError, transaction
from django.db.models import F
from django.utils import timezone

from medications.models import Medication
from medications.stock import StockError, apply_movement
from .models import Customer, Prescription, Sale, SaleItem, to_fcfa

# Remise maximale autorisée à la caisse, en pourcentage.
MAX_DISCOUNT = Decimal("20")

# Une ordonnance est acceptée pendant ce nombre de mois après sa date.
PRESCRIPTION_VALIDITY_MONTHS = 3


def oldest_valid_prescription_date(today=None):
    """
    Date de prescription la plus ancienne encore acceptée (incluse) :
    même jour, PRESCRIPTION_VALIDITY_MONTHS mois plus tôt. Un jour qui
    n'existe pas dans le mois visé (31 mai → 31 février) devient le dernier
    jour de ce mois.
    """
    today = today or timezone.localdate()
    month_index = today.year * 12 + (today.month - 1) - PRESCRIPTION_VALIDITY_MONTHS
    year, month = divmod(month_index, 12)
    month += 1
    last_day = calendar.monthrange(year, month)[1]
    return date(year, month, min(today.day, last_day))

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
    today = timezone.localdate()
    if prescription_date > today:
        raise SaleError("Ordonnance invalide : la date de prescription est dans le futur.")
    oldest = oldest_valid_prescription_date(today)
    if prescription_date < oldest:
        raise SaleError(
            f"Ordonnance expirée : elle date du {prescription_date:%d/%m/%Y} et n'est valable que "
            f"{PRESCRIPTION_VALIDITY_MONTHS} mois (au plus tôt le {oldest:%d/%m/%Y})."
        )
    return doctor_name, prescription_date


class _AlreadyCreated(Exception):
    """Une vente portant ce jeton a été validée pendant que l'on attendait les verrous."""


def _parse_token(raw):
    """Jeton de la caisse (UUID) ; absent pour les ventes créées hors caisse."""
    if raw in (None, ""):
        return None
    try:
        return uuid.UUID(str(raw))
    except ValueError:
        raise SaleError("Requête invalide.")


def _sale_with_token(user, token):
    sale = Sale.objects.filter(client_token=token).first()
    if sale is not None and sale.created_by_id != getattr(user, "pk", None):
        # Jeton d'un autre utilisateur : on ne révèle pas sa vente.
        raise SaleError("Requête invalide.")
    return sale


def create_sale(user, data):
    """
    Crée une vente complète à partir des données de la caisse.

    Lève SaleError pour toute donnée refusée ; rien n'est écrit dans ce cas.

    Idempotence : si `client_token` désigne une vente déjà enregistrée par
    cet utilisateur (double clic, relance après une coupure réseau), cette
    vente est renvoyée telle quelle, sans nouvelle écriture.
    """
    if not isinstance(data, dict):
        raise SaleError("Requête invalide.")

    token = _parse_token(data.get("client_token"))
    if token is not None:
        existing = _sale_with_token(user, token)
        if existing is not None:
            return existing

    try:
        return _create_sale(user, data, token)
    except (_AlreadyCreated, IntegrityError):
        # Deux requêtes simultanées avec le même jeton : la seconde est
        # annulée en entier (transaction) et renvoie la vente de la première.
        existing = _sale_with_token(user, token) if token is not None else None
        if existing is None:
            raise
        return existing


def _create_sale(user, data, token):
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

    customer_id = data.get("customer_id")
    if payment_method == "credit" and not customer_id:
        raise SaleError("Paiement à crédit : sélectionnez le client.")

    with transaction.atomic():
        customer = None
        if customer_id:
            try:
                # Verrou sur le client : son encours de crédit est relu et mis à
                # jour dans cette transaction, sans course avec une autre vente.
                customer = Customer.objects.select_for_update().get(pk=int(customer_id))
            except (TypeError, ValueError, Customer.DoesNotExist):
                raise SaleError("Client introuvable.")

        # Verrouille les médicaments (ordre stable pour éviter les interblocages)
        # et vérifie le stock avant toute écriture.
        medications = {
            med.id: med
            for med in Medication.objects.select_for_update().filter(id__in=quantities).order_by("id")
        }
        if len(medications) != len(quantities):
            raise SaleError("Un médicament du panier est introuvable.")
        # Une requête jumelle a pu valider la vente pendant que l'on attendait
        # ces verrous : on le vérifie avant de contrôler un stock déjà diminué.
        if token is not None and Sale.objects.filter(client_token=token).exists():
            raise _AlreadyCreated
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

        # Montants en francs CFA entiers. Le sous-total est la somme des
        # sous-totaux de ligne arrondis, exactement ceux de la facture.
        subtotal = sum(
            (to_fcfa(medications[med_id].selling_price * quantity) for med_id, quantity in quantities.items()),
            Decimal("0"),
        )
        total = subtotal - to_fcfa(subtotal * discount / 100)
        # Un montant remis avec des décimales (estimation du navigateur) est
        # ramené au franc près avant toute comparaison.
        amount_paid = to_fcfa(amount_paid)

        if payment_method == "especes":
            if amount_paid < total:
                raise SaleError(f"Montant payé insuffisant : {amount_paid} FCFA pour un total de {total} FCFA.")
        elif payment_method == "credit":
            if amount_paid > total:
                raise SaleError("Paiement à crédit : l'acompte ne peut pas dépasser le total.")
            due = total - amount_paid
            if due > customer.available_credit:
                raise SaleError(
                    f"Crédit insuffisant pour {customer.full_name} : "
                    f"disponible {customer.available_credit} FCFA, demandé {due} FCFA."
                )
            Customer.objects.filter(pk=customer.pk).update(current_credit=F("current_credit") + due)
        else:
            # Carte ou mobile money : le montant débité est exactement le total.
            amount_paid = total

        sale = Sale(
            customer=customer,
            subtotal=subtotal,
            discount_percentage=discount,
            payment_method=payment_method,
            amount_paid=amount_paid,
            created_by=user,
            status="completee",
            client_token=token,
        )
        sale.save()

        for med_id, quantity in quantities.items():
            med = medications[med_id]
            SaleItem.objects.create(
                sale=sale,
                medication=med,
                quantity=quantity,
                unit_price=med.selling_price,
                unit_cost=med.purchase_price,
            )
            try:
                apply_movement(
                    med, "sortie", quantity, user=user,
                    reason=f"Vente #{sale.sale_number}", reference=sale.sale_number,
                )
            except StockError as e:
                raise SaleError(str(e))

        if prescription_info:
            doctor_name, prescription_date = prescription_info
            Prescription.objects.create(
                customer=customer,
                sale=sale,
                doctor_name=doctor_name,
                prescription_date=prescription_date,
            )

    return sale
