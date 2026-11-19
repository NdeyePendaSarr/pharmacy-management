"""Point 9 : tableau de bord en requêtes groupées, filtres de stock en base."""
from datetime import timedelta
from decimal import Decimal

from django.db.models.query import QuerySet
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from pharmanps_alou.testing import make_medication, make_user
from sales import services
from sales.models import Sale

# Avant : 33 requêtes (deux boucles de 7 jours avec 2 à 3 requêtes par jour).
# Après : session, utilisateur, permissions (4) + 5 requêtes de données.
DASHBOARD_QUERIES = 9


class DashboardTests(TestCase):
    def setUp(self):
        self.client.force_login(make_user(groups=["Pharmacien"]))
        self.today = timezone.localdate()

    def sell(self, amount, days_ago=0, quantity=1):
        med = make_medication(selling_price=Decimal(amount))
        sale = services.create_sale(None, {
            "items": [{"medication_id": med.id, "quantity": quantity}],
            "payment_method": "carte",
        })
        if days_ago:
            moment = timezone.now() - timedelta(days=days_ago)
            Sale.objects.filter(pk=sale.pk).update(created_at=moment)
        return med

    def test_query_count_does_not_depend_on_the_data(self):
        with self.assertNumQueries(DASHBOARD_QUERIES):
            self.client.get(reverse("dashboard"))
        for days_ago in range(10):
            self.sell("1000", days_ago=days_ago)
        with self.assertNumQueries(DASHBOARD_QUERIES):
            self.client.get(reverse("dashboard"))

    def test_figures_are_unchanged(self):
        self.sell("1000")
        self.sell("2500")
        self.sell("400", days_ago=2)
        self.sell("9000", days_ago=40)
        context = self.client.get(reverse("dashboard")).context

        self.assertEqual(context["total_sales"], 2)
        self.assertEqual(context["total_sales_amount"], Decimal("3500"))
        self.assertEqual(context["ca_jour"], Decimal("3500"))
        self.assertEqual(context["ca_total"], Decimal("12900"))
        monday = self.today - timedelta(days=self.today.weekday())
        expected_week = Decimal("3500") + (Decimal("400") if self.today - timedelta(days=2) >= monday else 0)
        self.assertEqual(context["ca_semaine"], expected_week)

        labels = [(self.today - timedelta(days=i)).strftime("%d/%m") for i in range(6, -1, -1)]
        self.assertEqual(context["chart_sales_labels"], labels)
        self.assertEqual(context["chart_sales_data"], [0.0, 0.0, 0.0, 0.0, 400.0, 0.0, 3500.0])

        recap = context["recap_jours"]
        self.assertEqual(len(recap), 7)
        self.assertEqual(recap[0], {"date": self.today.strftime("%d/%m/%Y"), "montant": 3500.0, "nombre": 2})
        self.assertEqual(recap[2]["nombre"], 1)

    def test_top_products(self):
        best = self.sell("1000", quantity=5)
        self.sell("1000", quantity=2)
        context = self.client.get(reverse("dashboard")).context
        self.assertEqual(context["chart_products_labels"][0], best.name)
        self.assertEqual(context["chart_products_data"][:2], [5, 2])


class MedicationStockFilterTests(TestCase):
    def setUp(self):
        self.client.force_login(make_user(groups=["Pharmacien"]))
        today = timezone.localdate()
        self.low = make_medication(name="Stock bas", quantity=3, min_quantity=10)
        self.expired = make_medication(name="Périmé", expiry_date=today - timedelta(days=1))
        self.expiring = make_medication(name="Bientôt périmé", expiry_date=today + timedelta(days=10))
        self.ok = make_medication(name="Normal", quantity=100, min_quantity=10)

    def names(self, stock_filter):
        # Liste paginée : le paginateur reçoit un queryset filtré en base.
        medications = self.client.get(reverse("medication_list"), {"stock": stock_filter}).context["page_obj"].paginator.object_list
        self.assertIsInstance(medications, QuerySet)
        return {med.name for med in medications}

    def test_filters_stay_querysets(self):
        self.assertEqual(self.names("low"), {"Stock bas"})
        self.assertEqual(self.names("expired"), {"Périmé"})
        self.assertEqual(self.names("expiring"), {"Bientôt périmé"})
