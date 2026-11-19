from django import forms
from django.core.validators import MinValueValidator
from django.utils import timezone

from .models import Category, Medication, StockMovement


class MedicationForm(forms.ModelForm):
    """
    Fiche médicament. La quantité en stock n'en fait pas partie : à la
    création, `quantity` est le stock initial, enregistré comme mouvement
    d'entrée ; ensuite, seul un mouvement de stock peut la changer.
    """

    quantity = forms.IntegerField(
        label="Stock initial", min_value=0, required=False, initial=0,
        help_text="Enregistré comme mouvement d'entrée.",
    )

    class Meta:
        model = Medication
        fields = [
            "name", "dci", "barcode", "category", "form", "dosage",
            "purchase_price", "selling_price", "min_quantity", "expiry_date",
            "location", "requires_prescription", "image", "description",
        ]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if self.instance.pk:
            del self.fields["quantity"]
        # Une catégorie supprimée laisse ses médicaments sans catégorie
        # (on_delete=SET_NULL) : leur fiche doit rester modifiable.
        self.fields["category"].required = False
        self.fields["min_quantity"].validators.append(MinValueValidator(0))
        self.fields["min_quantity"].widget.attrs["min"] = 0

    def _clean_price(self, field):
        price = self.cleaned_data.get(field)
        if price is not None and price <= 0:
            raise forms.ValidationError("Le prix doit être supérieur à 0.")
        if price is not None and price != price.to_integral_value():
            raise forms.ValidationError("Le prix doit être un nombre entier de francs CFA.")
        return price

    def clean_purchase_price(self):
        return self._clean_price("purchase_price")

    def clean_selling_price(self):
        return self._clean_price("selling_price")

    def clean_expiry_date(self):
        expiry_date = self.cleaned_data.get("expiry_date")
        # Un médicament déjà en stock peut être périmé (il faut pouvoir corriger
        # sa fiche) ; en revanche on n'enregistre pas un nouveau produit périmé.
        if expiry_date and not self.instance.pk and expiry_date < timezone.localdate():
            raise forms.ValidationError("La date de péremption est déjà dépassée.")
        return expiry_date

    def clean(self):
        cleaned = super().clean()
        purchase, selling = cleaned.get("purchase_price"), cleaned.get("selling_price")
        if purchase and selling and selling < purchase:
            self.add_error("selling_price", "Le prix de vente doit être supérieur ou égal au prix d'achat.")
        return cleaned


class CategoryForm(forms.ModelForm):
    class Meta:
        model = Category
        fields = ["name", "description"]


class StockMovementForm(forms.ModelForm):
    class Meta:
        model = StockMovement
        fields = ["movement_type", "quantity", "reason", "reference"]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["quantity"].validators.append(MinValueValidator(1))
        self.fields["quantity"].widget.attrs["min"] = 1
        self.fields["reason"].required = False
        self.fields["reference"].required = False
