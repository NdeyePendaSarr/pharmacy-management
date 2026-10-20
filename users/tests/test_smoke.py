"""Chaque page de l'application s'affiche sans erreur pour un Pharmacien."""
from django.test import TestCase
from django.urls import reverse

from pharmanps_alou.testing import make_category, make_customer, make_medication, make_user
from sales import services


class PagesRenderTests(TestCase):
    def setUp(self):
        self.client.force_login(make_user(groups=["Pharmacien"]))
        self.category = make_category()
        self.medication = make_medication(category=self.category)
        self.customer = make_customer()
        self.sale = services.create_sale(None, {
            "items": [{"medication_id": self.medication.id, "quantity": 1}],
            "payment_method": "carte",
            "customer_id": self.customer.id,
        })

    def test_every_page_renders(self):
        pages = [
            reverse("dashboard"),
            reverse("pos"),
            reverse("medication_list"),
            reverse("medication_list") + "?stock=low",
            reverse("medication_list") + "?stock=expired",
            reverse("medication_list") + "?stock=expiring",
            reverse("medication_create"),
            reverse("medication_detail", args=[self.medication.pk]),
            reverse("medication_update", args=[self.medication.pk]),
            reverse("medication_delete", args=[self.medication.pk]),
            reverse("stock_movement_create", args=[self.medication.pk]),
            reverse("category_list"),
            reverse("category_create"),
            reverse("category_update", args=[self.category.pk]),
            reverse("category_delete", args=[self.category.pk]),
            reverse("sale_list"),
            reverse("sale_detail", args=[self.sale.pk]),
            reverse("sale_invoice", args=[self.sale.pk]),
            reverse("customer_list"),
            reverse("customer_create"),
            reverse("customer_detail", args=[self.customer.pk]),
            reverse("customer_update", args=[self.customer.pk]),
            reverse("customer_sales", args=[self.customer.pk]),
            reverse("search_medication") + "?q=Médicament",
        ]
        for url in pages:
            with self.subTest(url=url):
                self.assertEqual(self.client.get(url).status_code, 200)

    def test_health_check(self):
        self.client.logout()
        self.assertEqual(self.client.get(reverse("health")).json(), {"status": "ok"})
