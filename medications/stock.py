"""
Seul point d'écriture du stock.

Chaque changement de quantité passe par apply_movement : la ligne du
médicament est verrouillée (SELECT ... FOR UPDATE), le contrôle « jamais
sous zéro » est fait sur la valeur verrouillée, puis la quantité est mise
à jour avec F() et le mouvement est enregistré, le tout dans une seule
transaction. Deux opérations simultanées s'exécutent donc l'une après
l'autre, sans écraser le résultat de l'autre.
"""
from django.db import transaction
from django.db.models import F
from django.utils import timezone

from .models import Medication, StockMovement

ALL_TYPES = StockMovement.INBOUND_TYPES | StockMovement.OUTBOUND_TYPES


class StockError(Exception):
    """Mouvement refusé ; le message peut être montré à l'utilisateur."""


def apply_movement(medication, movement_type, quantity, *, user=None, reason="", reference=""):
    if movement_type not in ALL_TYPES:
        raise StockError("Type de mouvement invalide.")
    if isinstance(quantity, bool) or not isinstance(quantity, int) or quantity <= 0:
        raise StockError("La quantité doit être un nombre entier strictement positif.")

    delta = quantity if movement_type in StockMovement.INBOUND_TYPES else -quantity

    with transaction.atomic():
        locked = Medication.objects.select_for_update().get(pk=medication.pk)
        if locked.quantity + delta < 0:
            raise StockError(
                f'Stock insuffisant pour "{locked.name}" '
                f"(disponible : {locked.quantity}, demandé : {quantity})."
            )
        Medication.objects.filter(pk=locked.pk).update(
            quantity=F("quantity") + delta, updated_at=timezone.now()
        )
        movement = StockMovement.objects.create(
            medication=locked,
            movement_type=movement_type,
            quantity=quantity,
            reason=reason or None,
            reference=reference or None,
            created_by=user,
        )

    # L'instance de l'appelant reflète le nouveau stock.
    medication.quantity = locked.quantity + delta
    return movement
