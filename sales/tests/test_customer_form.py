"""Point 7 : validation du formulaire client et protection des champs sensibles."""
from decimal import Decimal

from django.contrib.auth.models import Permission
from django.test import TestCase
from django.urls import reverse

from pharmanps_alou.testing import make_customer, make_user
from sales.models import Customer


class CustomerFormTests(TestCase):
    def setUp(self):
        self.client.force_login(make_user(groups=["Pharmacien"]))

    def data(self, **overrides):
        values = {
            "first_name": "Awa",
            "last_name": "Ndiaye",
            "phone": "+221 77 000 00 00",
            "customer_type": "particulier",
            "credit_limit": "10000",
            "date_of_birth": "1990-04-12",
            "medical_conditions": "Asthme",
        }
        values.update(overrides)
        return values

    def test_valid_creation(self):
        response = self.client.post(reverse("customer_create"), self.data())
        self.assertRedirects(response, reverse("customer_list"))
        customer = Customer.objects.get()
        self.assertEqual(customer.credit_limit, Decimal("10000"))
        self.assertEqual(customer.medical_conditions, "Asthme")

    def test_invalid_values_are_refused_without_raw_error(self):
        invalid = [
            {"credit_limit": "-1"},
            {"credit_limit": "beaucoup"},
            {"date_of_birth": "1990-13-45"},
            {"phone": ""},
            {"customer_type": "vip"},
            {"email": "pas-un-email"},
        ]
        for overrides in invalid:
            with self.subTest(overrides=overrides):
                response = self.client.post(reverse("customer_create"), self.data(**overrides))
                self.assertEqual(response.status_code, 200)
                self.assertContains(response, "Le formulaire contient des erreurs")
                self.assertNotContains(response, "Traceback")
        self.assertFalse(Customer.objects.exists())

    def test_update(self):
        customer = make_customer(credit_limit=Decimal("0"))
        response = self.client.post(reverse("customer_update", args=[customer.pk]), self.data(credit_limit="2500.50"))
        self.assertRedirects(response, reverse("customer_detail", args=[customer.pk]))
        customer.refresh_from_db()
        self.assertEqual(customer.credit_limit, Decimal("2500.50"))
        self.assertEqual(customer.last_name, "Ndiaye")


class SensitiveFieldsFormTests(TestCase):
    """Un compte qui peut modifier un client sans la permission « données sensibles »."""

    def setUp(self):
        user = make_user()
        user.user_permissions.add(
            *Permission.objects.filter(codename__in=["add_customer", "change_customer", "view_customer"])
        )
        self.client.force_login(user)
        self.customer = make_customer(medical_conditions="Diabète", date_of_birth="1980-01-01")

    def test_sensitive_fields_are_neither_shown_nor_writable(self):
        url = reverse("customer_update", args=[self.customer.pk])
        page = self.client.get(url)
        self.assertNotContains(page, 'name="medical_conditions"')
        self.assertNotContains(page, "Diabète")
        self.client.post(url, {
            "first_name": "Awa", "last_name": "Ndiaye", "phone": "770000000",
            "customer_type": "particulier", "credit_limit": "0",
            "medical_conditions": "Effacé", "date_of_birth": "2000-01-01",
        })
        self.customer.refresh_from_db()
        self.assertEqual(self.customer.medical_conditions, "Diabète")
        self.assertEqual(str(self.customer.date_of_birth), "1980-01-01")
