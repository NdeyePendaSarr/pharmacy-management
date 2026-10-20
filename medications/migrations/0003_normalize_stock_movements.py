"""
Prépare les données existantes aux nouvelles règles de stock, avant l'ajout
des contraintes (migration 0004) :

- l'ancien type « ajustement » ajoutait sa quantité au stock : une quantité
  positive devient « ajustement_plus », une quantité négative devient
  « ajustement_moins » avec sa valeur absolue ;
- un mouvement d'un autre type saisi avec une quantité négative est
  converti en ajustement de sens équivalent (même effet sur le stock) ;
- un mouvement de quantité nulle n'a eu aucun effet : il est supprimé ;
- un stock négatif (hérité d'anciennes anomalies) est ramené à 0 par un
  mouvement « ajustement_plus » tracé, pour que l'historique reste juste.

Les variations de stock déjà produites sont conservées à l'identique.
"""
from django.db import migrations

INBOUND = {"entrée", "retour", "ajustement", "ajustement_plus"}


def normalize(apps, schema_editor):
    StockMovement = apps.get_model("medications", "StockMovement")
    Medication = apps.get_model("medications", "Medication")

    StockMovement.objects.filter(quantity=0).delete()

    for movement in StockMovement.objects.filter(movement_type="ajustement"):
        if movement.quantity > 0:
            movement.movement_type = "ajustement_plus"
        else:
            movement.movement_type = "ajustement_moins"
            movement.quantity = -movement.quantity
        movement.save(update_fields=["movement_type", "quantity"])

    for movement in StockMovement.objects.filter(quantity__lt=0):
        was_inbound = movement.movement_type in INBOUND
        note = f"[Migration] Ancien mouvement « {movement.movement_type} » de quantité {movement.quantity}."
        movement.movement_type = "ajustement_moins" if was_inbound else "ajustement_plus"
        movement.quantity = -movement.quantity
        movement.reason = f"{movement.reason}\n{note}" if movement.reason else note
        movement.save(update_fields=["movement_type", "quantity", "reason"])

    for medication in Medication.objects.filter(quantity__lt=0):
        StockMovement.objects.create(
            medication=medication,
            movement_type="ajustement_plus",
            quantity=-medication.quantity,
            reason="[Migration] Stock négatif ramené à 0 avant l'ajout de la contrainte « stock ≥ 0 ».",
        )
        medication.quantity = 0
        medication.save(update_fields=["quantity"])


class Migration(migrations.Migration):

    dependencies = [
        ("medications", "0002_alter_medication_image"),
    ]

    operations = [
        migrations.RunPython(normalize, migrations.RunPython.noop),
    ]
