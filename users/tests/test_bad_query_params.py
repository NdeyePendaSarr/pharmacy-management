"""Des paramètres d'URL invalides sont ignorés : jamais d'erreur 500."""
from datetime import timedelta
from decimal import Decimal

from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from pharmanps_alou.testing import make_category, make_medication, make_user
from sales import services


class BadQueryParamsTests(TestCase):
    def setUp(self):
        self.client.force_login(make_user(groups=["Pharmacien"]))

    def test_invalid_category_is_ignored(self):
        make_medication()
        url = reverse("medication_list")
        for value in ("abc", "1;DROP", "²", "99999999999999999999999", "-1"):
            with self.subTest(category=value):
                response = self.client.get(url, {"category": value})
                self.assertEqual(response.status_code, 200)
                self.assertEqual(response.context["category_filter"], "")
                self.assertEqual(len(response.context["medications"]), 1)

    def test_valid_category_still_filters(self):
        category = make_category()
        make_medication(category=category)
        make_medication()
        response = self.client.get(reverse("medication_list"), {"category": str(category.pk)})
        self.assertEqual(len(response.context["medications"]), 1)

    def test_invalid_date_is_ignored(self):
        url = reverse("sale_list")
        for value in ("abc", "2026-13-45", "2026-02-30", "19/11/2026"):
            with self.subTest(date=value):
                response = self.client.get(url, {"date": value})
                self.assertEqual(response.status_code, 200)
                self.assertEqual(response.context["date_filter"], "")

    def test_valid_date_still_filters(self):
        medication = make_medication(selling_price=Decimal("1000"))
        services.create_sale(None, {
            "items": [{"medication_id": medication.id, "quantity": 1}],
            "payment_method": "carte",
        })
        today = timezone.localdate()
        url = reverse("sale_list")
        self.assertEqual(len(self.client.get(url, {"date": today.isoformat()}).context["sales"]), 1)
        yesterday = (today - timedelta(days=1)).isoformat()
        self.assertEqual(len(self.client.get(url, {"date": yesterday}).context["sales"]), 0)
