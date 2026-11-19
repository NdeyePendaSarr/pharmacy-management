"""
Une ordonnance n'est acceptée que pendant 3 mois après sa date, et elle
reste visible sur la vente et sur la facture.
"""
from datetime import date, timedelta
from unittest import mock

from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from pharmanps_alou.testing import make_customer, make_medication, make_user
from sales import services
from sales.models import Sale


class OldestValidDateTests(TestCase):
    def test_three_calendar_months_earlier(self):
        self.assertEqual(services.oldest_valid_prescription_date(date(2026, 11, 19)), date(2026, 8, 19))

    def test_crosses_the_year(self):
        self.assertEqual(services.oldest_valid_prescription_date(date(2026, 2, 10)), date(2025, 11, 10))

    def test_missing_day_becomes_end_of_month(self):
        # 31 mai − 3 mois : il n'y a pas de 31 février.
        self.assertEqual(services.oldest_valid_prescription_date(date(2026, 5, 31)), date(2026, 2, 28))
        self.assertEqual(services.oldest_valid_prescription_date(date(2028, 5, 31)), date(2028, 2, 29))


class PrescriptionValidityTests(TestCase):
    today = date(2026, 11, 19)

    def setUp(self):
        self.user = make_user(groups=["Vendeur"])
        self.customer = make_customer()
        self.antibiotic = make_medication(requires_prescription=True, expiry_date=date(2030, 1, 1))
        patcher = mock.patch("django.utils.timezone.localdate", return_value=self.today)
        patcher.start()
        self.addCleanup(patcher.stop)

    def sell(self, prescription_date):
        return services.create_sale(self.user, {
            "items": [{"medication_id": self.antibiotic.id, "quantity": 1}],
            "payment_method": "carte",
            "customer_id": self.customer.id,
            "prescription": {"doctor_name": "Dr Fall", "prescription_date": prescription_date.isoformat()},
        })

    def test_prescription_of_exactly_three_months_is_accepted(self):
        self.sell(date(2026, 8, 19))
        self.assertEqual(Sale.objects.count(), 1)

    def test_prescription_older_than_three_months_is_refused(self):
        for old in (date(2026, 8, 18), date(1990, 1, 1)):
            with self.subTest(prescription_date=old):
                with self.assertRaisesMessage(services.SaleError, "Ordonnance expirée"):
                    self.sell(old)
        self.assertFalse(Sale.objects.exists())
        self.antibiotic.refresh_from_db()
        self.assertEqual(self.antibiotic.quantity, 50)

    def test_refusal_message_gives_the_limit(self):
        with self.assertRaisesMessage(services.SaleError, "au plus tôt le 19/08/2026"):
            self.sell(date(2026, 1, 1))

    def test_vendeur_can_sell_with_a_valid_prescription(self):
        sale = self.sell(self.today - timedelta(days=10))
        self.assertEqual(sale.created_by, self.user)
        self.assertEqual(sale.prescription.doctor_name, "Dr Fall")


class PrescriptionDisplayTests(TestCase):
    def setUp(self):
        self.user = make_user(groups=["Vendeur"])
        self.client.force_login(self.user)
        antibiotic = make_medication(requires_prescription=True)
        self.prescription_date = timezone.localdate() - timedelta(days=5)
        self.sale = services.create_sale(self.user, {
            "items": [{"medication_id": antibiotic.id, "quantity": 1}],
            "payment_method": "carte",
            "customer_id": make_customer().id,
            "prescription": {"doctor_name": "Dr Aminata Fall", "prescription_date": self.prescription_date.isoformat()},
        })

    def test_sale_detail_and_invoice_show_the_prescription(self):
        for name in ("sale_detail", "sale_invoice"):
            with self.subTest(page=name):
                html = self.client.get(reverse(name, args=[self.sale.pk])).content.decode()
                self.assertIn("Dr Aminata Fall", html)
                self.assertIn(f"{self.prescription_date:%d/%m/%Y}", html)

    def test_till_shows_the_validity_rule(self):
        html = self.client.get(reverse("pos")).content.decode()
        oldest = services.oldest_valid_prescription_date()
        self.assertIn(f'min="{oldest:%Y-%m-%d}"', html)
        self.assertIn("valable 3 mois", html)
