from django import forms
from django.core.validators import MinValueValidator

from .models import Customer

SENSITIVE_FIELDS = ("date_of_birth", "medical_conditions")


class CustomerForm(forms.ModelForm):
    """
    Fiche client. Sans la permission sales.view_sensitive_customer, les
    champs médicaux ne sont ni affichés ni modifiables.
    """

    class Meta:
        model = Customer
        fields = [
            "first_name", "last_name", "phone", "email", "address",
            "date_of_birth", "customer_type", "medical_conditions", "credit_limit",
        ]

    def __init__(self, *args, user, **kwargs):
        super().__init__(*args, **kwargs)
        if not user.has_perm("sales.view_sensitive_customer"):
            for name in SENSITIVE_FIELDS:
                del self.fields[name]
        self.fields["credit_limit"].validators.append(MinValueValidator(0))
        self.fields["credit_limit"].widget.attrs["min"] = 0

    @property
    def shows_sensitive_fields(self):
        return "medical_conditions" in self.fields
