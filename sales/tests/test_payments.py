"""Point 6 : numéro de vente, monnaie rendue, paiement à crédit, coût d'achat figé."""
import json
import threading
import unittest
from decimal import Decimal

from django.db import connection
from django.test import Client, TestCase, TransactionTestCase
from django.urls import reverse

from pharmanps_alou.testing import make_customer, make_medication, make_user
from sales.models import Sale


def post_sale(client, **payload):
    return client.post(reverse("create_sale"), data=json.dumps(payload), content_type="application/json")


class SaleTestBase(TestCase):
    def setUp(self):
        self.client.force_login(make_user(groups=["Vendeur"]))
        # 2 boîtes à 1 000 FCFA = 2 000 FCFA ; prix d'achat 600 FCFA.
        self.med = make_medication(selling_price=Decimal("1000"), purchase_price=Decimal("600"), quantity=50)

    def sell(self, **payload):
        payload.setdefault("items", [{"medication_id": self.med.id, "quantity": 2}])
        return post_sale(self.client, **payload)


class SaleNumberTests(SaleTestBase):
    def test_numbers_are_unique_even_after_a_deletion(self):
        first = self.sell(payment_method="carte").json()
        self.sell(payment_method="carte")
        # L'ancien numéro « nombre de ventes du jour + 1 » retombait sur un numéro existant.
        Sale.objects.filter(pk=first["sale_id"]).delete()
        response = self.sell(payment_method="carte")
        self.assertEqual(response.status_code, 200, response.content)
        numbers = list(Sale.objects.values_list("sale_number", flat=True))
        self.assertEqual(len(numbers), len(set(numbers)))

    def test_number_is_derived_from_the_sale_id(self):
        sale = Sale.objects.get(pk=self.sell(payment_method="carte").json()["sale_id"])
        self.assertTrue(sale.sale_number.endswith(f"-{sale.pk:06d}"), sale.sale_number)


class CashPaymentTests(SaleTestBase):
    def test_change_is_computed_by_the_server(self):
        response = self.sell(payment_method="especes", amount_paid="2500")
        self.assertEqual(response.status_code, 200, response.content)
        sale = Sale.objects.get()
        self.assertEqual(sale.amount_paid, Decimal("2500.00"))
        self.assertEqual(sale.change_amount, Decimal("500.00"))

    def test_insufficient_cash_is_refused(self):
        response = self.sell(payment_method="especes", amount_paid="1500")
        self.assertEqual(response.status_code, 400)
        self.assertFalse(Sale.objects.exists())

    def test_card_payment_is_exactly_the_total(self):
        response = self.sell(payment_method="carte", amount_paid="1")
        self.assertEqual(response.status_code, 200, response.content)
        sale = Sale.objects.get()
        self.assertEqual(sale.amount_paid, Decimal("2000.00"))
        self.assertEqual(sale.change_amount, Decimal("0"))

    def test_change_is_reset_when_payment_no_longer_exceeds_total(self):
        self.sell(payment_method="especes", amount_paid="2500")
        sale = Sale.objects.get()
        sale.amount_paid = Decimal("2000")
        sale.save()
        self.assertEqual(sale.change_amount, Decimal("0"))


class CreditPaymentTests(SaleTestBase):
    def test_credit_requires_a_customer(self):
        response = self.sell(payment_method="credit")
        self.assertEqual(response.status_code, 400)
        self.assertIn("client", response.json()["message"].lower())

    def test_credit_beyond_available_credit_is_refused(self):
        customer = make_customer(credit_limit=Decimal("5000"), current_credit=Decimal("4000"))
        response = self.sell(payment_method="credit", customer_id=customer.id)
        self.assertEqual(response.status_code, 400)
        customer.refresh_from_db()
        self.assertEqual(customer.current_credit, Decimal("4000"))
        self.assertFalse(Sale.objects.exists())

    def test_credit_sale_increases_customer_debt(self):
        customer = make_customer(credit_limit=Decimal("5000"), current_credit=Decimal("1000"))
        response = self.sell(payment_method="credit", customer_id=customer.id)
        self.assertEqual(response.status_code, 200, response.content)
        customer.refresh_from_db()
        self.assertEqual(customer.current_credit, Decimal("3000.00"))
        sale = Sale.objects.get()
        self.assertEqual(sale.amount_paid, Decimal("0"))
        self.assertEqual(sale.change_amount, Decimal("0"))

    def test_down_payment_reduces_the_amount_on_credit(self):
        customer = make_customer(credit_limit=Decimal("1500"))
        response = self.sell(payment_method="credit", customer_id=customer.id, amount_paid="500")
        self.assertEqual(response.status_code, 200, response.content)
        customer.refresh_from_db()
        self.assertEqual(customer.current_credit, Decimal("1500.00"))


class UnitCostTests(SaleTestBase):
    def test_profit_uses_the_purchase_price_at_the_time_of_sale(self):
        self.sell(payment_method="carte")
        sale = Sale.objects.get()
        self.assertEqual(sale.items.get().unit_cost, Decimal("600.00"))
        self.assertEqual(sale.profit, Decimal("800.00"))
        # Une hausse ultérieure du prix d'achat ne réécrit pas le passé.
        self.med.purchase_price = Decimal("900")
        self.med.save()
        sale.refresh_from_db()
        self.assertEqual(sale.profit, Decimal("800.00"))


@unittest.skipUnless(connection.vendor == "postgresql", "concurrence réelle : PostgreSQL requis")
class ConcurrentSaleNumberTests(TransactionTestCase):
    def test_simultaneous_sales_get_distinct_numbers(self):
        user = make_user(groups=["Vendeur"])
        meds = [make_medication(quantity=10), make_medication(quantity=10)]
        barrier = threading.Barrier(2)
        statuses = []

        def worker(med):
            client = Client()
            client.force_login(user)
            barrier.wait()
            try:
                response = post_sale(client, items=[{"medication_id": med.id, "quantity": 1}], payment_method="carte")
                statuses.append(response.status_code)
            finally:
                connection.close()

        threads = [threading.Thread(target=worker, args=(med,)) for med in meds]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()

        self.assertEqual(statuses, [200, 200])
        numbers = list(Sale.objects.values_list("sale_number", flat=True))
        self.assertEqual(len(set(numbers)), 2)
