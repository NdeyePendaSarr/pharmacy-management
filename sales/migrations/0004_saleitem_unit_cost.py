"""
Ajoute SaleItem.unit_cost (prix d'achat figé au moment de la vente).

Pour les lignes existantes, le prix d'achat d'origine n'a jamais été
enregistré : on reprend le prix d'achat actuel du médicament, la meilleure
valeur disponible (c'est d'ailleurs celle qu'utilisait l'ancien calcul du
bénéfice). Les nouvelles ventes enregistrent leur propre coût.
"""
from django.db import migrations, models
from django.db.models import OuterRef, Subquery


def fill_unit_cost(apps, schema_editor):
    SaleItem = apps.get_model("sales", "SaleItem")
    Medication = apps.get_model("medications", "Medication")
    SaleItem.objects.filter(unit_cost__isnull=True).update(
        unit_cost=Subquery(Medication.objects.filter(pk=OuterRef("medication_id")).values("purchase_price")[:1])
    )


class Migration(migrations.Migration):

    dependencies = [
        ("medications", "0004_stock_constraints"),
        ("sales", "0003_customer_sensitive_permission"),
    ]

    operations = [
        migrations.AddField(
            model_name="saleitem",
            name="unit_cost",
            field=models.DecimalField(decimal_places=2, max_digits=10, null=True, verbose_name="Coût d'achat unitaire"),
        ),
        migrations.RunPython(fill_unit_cost, migrations.RunPython.noop),
        migrations.AlterField(
            model_name="saleitem",
            name="unit_cost",
            field=models.DecimalField(decimal_places=2, max_digits=10, verbose_name="Coût d'achat unitaire"),
        ),
    ]
