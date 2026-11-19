"""Point 1 : les montants d'une vente sont calculés par le serveur, jamais par le navigateur."""
import json
from decimal import Decimal
from unittest import mock

from django.test import TestCase
from django.urls import reverse

from pharmanps_alou.testing import make_medication, make_user
from sales.models import Sale


class CreateSaleTestMixin:
    def setUp(self):
        self.user = make_user(superuser=True)
        self.client.force_login(self.user)
        self.med = make_medication(selling_price=Decimal("1000.00"), quantity=50)

    def post_sale(self, **overrides):
        payload = {
            # Le navigateur envoie aussi ses propres prix : le serveur doit les ignorer.
            "items": [{"medication_id": self.med.id, "quantity": 2, "unit_price": 1000}],
            "subtotal": 2000,
            "discount_percentage": 0,
            "payment_method": "carte",
            "amount_paid": 0,
        }
        payload.update(overrides)
        return self.client.post(
            reverse("create_sale"), data=json.dumps(payload), content_type="application/json"
        )


class ServerSidePricingTests(CreateSaleTestMixin, TestCase):
    def test_falsified_prices_are_ignored(self):
        response = self.post_sale(
            items=[{"medication_id": self.med.id, "quantity": 2, "unit_price": 1, "subtotal": 2}],
            subtotal=2,
            total=2,
        )
        self.assertEqual(response.status_code, 200, response.content)
        sale = Sale.objects.get()
        item = sale.items.get()
        self.assertEqual(item.unit_price, Decimal("1000.00"))
        self.assertEqual(item.subtotal, Decimal("2000.00"))
        self.assertEqual(sale.subtotal, Decimal("2000.00"))
        self.assertEqual(sale.total, Decimal("2000.00"))

    def test_amounts_are_exact_decimals(self):
        # 333 × 3 = 999 ; 10 % = 99,9 → 100 ; total 899 (Decimal, sans erreur de flottant).
        self.med.selling_price = Decimal("333")
        self.med.save()
        response = self.post_sale(
            items=[{"medication_id": self.med.id, "quantity": 3, "unit_price": 333.33}],
            subtotal=999.99,
            discount_percentage="10",
        )
        self.assertEqual(response.status_code, 200, response.content)
        sale = Sale.objects.get()
        self.assertEqual(sale.subtotal, Decimal("999"))
        self.assertEqual(sale.discount_amount, Decimal("100"))
        self.assertEqual(sale.total, Decimal("899"))

    def test_discount_above_max_is_refused(self):
        response = self.post_sale(discount_percentage=50)
        self.assertEqual(response.status_code, 400)
        self.assertFalse(Sale.objects.exists())

    def test_total_is_never_negative(self):
        for discount in (150, -10):
            with self.subTest(discount=discount):
                response = self.post_sale(discount_percentage=discount)
                self.assertEqual(response.status_code, 400)
        self.assertFalse(Sale.objects.exists())
        self.med.refresh_from_db()
        self.assertEqual(self.med.quantity, 50)

    def test_unknown_payment_method_is_refused(self):
        response = self.post_sale(payment_method="cheque-en-bois")
        self.assertEqual(response.status_code, 400)
        self.assertFalse(Sale.objects.exists())

    def test_quantities_must_be_positive_integers(self):
        for quantity in (0, -1, 1.5, "2.5", "abc", True, None):
            with self.subTest(quantity=quantity):
                response = self.post_sale(items=[{"medication_id": self.med.id, "quantity": quantity, "unit_price": 1000}]
                )
                self.assertEqual(response.status_code, 400)
        self.assertFalse(Sale.objects.exists())

    def test_unexpected_error_does_not_leak_details(self):
        with mock.patch("sales.views.services.create_sale", side_effect=RuntimeError("détail interne secret")):
            with self.assertLogs("sales.views", level="ERROR"):
                response = self.post_sale()
        self.assertEqual(response.status_code, 500)
        self.assertNotIn("détail interne secret", response.content.decode())
        self.assertFalse(response.json()["success"])

    def test_till_shows_the_maximum_discount(self):
        response = self.client.get(reverse("pos"))
        self.assertContains(response, 'max="20"')
