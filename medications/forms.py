from django import forms
from django.core.validators import MinValueValidator

from .models import StockMovement


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
