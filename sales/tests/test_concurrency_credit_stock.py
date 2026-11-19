"""
Concurrence réelle (deux fils, PostgreSQL) :
- deux ventes à crédit simultanées ne dépassent pas ensemble le plafond du client ;
- une vente et une sortie de stock manuelle simultanées ne vident pas le stock sous zéro.
"""
import json
import threading
import unittest
from decimal import Decimal

from django.db import connection
from django.test import Client, TransactionTestCase
from django.urls import reverse

from pharmanps_alou.testing import make_customer, make_medication, make_user
from sales.models import Sale


def run_together(*actions):
    """Lance les actions en même temps (barrière) et renvoie leurs résultats dans l'ordre."""
    barrier = threading.Barrier(len(actions))
    results = [None] * len(actions)

    def worker(index, action):
        barrier.wait()
        try:
            results[index] = action()
        finally:
            connection.close()

    threads = [threading.Thread(target=worker, args=(i, a)) for i, a in enumerate(actions)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    return results


def logged_client(user):
    client = Client()
    client.force_login(user)
    return client


@unittest.skipUnless(connection.vendor == "postgresql", "concurrence réelle : PostgreSQL requis")
class ConcurrentCreditTests(TransactionTestCase):
    def test_two_credit_sales_cannot_exceed_the_limit_together(self):
        vendeur = make_user(groups=["Vendeur"])
        medication = make_medication(quantity=50, selling_price=Decimal("1000"))
        # Plafond 1 500 : une vente de 1 000 passe, deux non.
        customer = make_customer(credit_limit=Decimal("1500"))
        payload = json.dumps({
            "items": [{"medication_id": medication.id, "quantity": 1}],
            "payment_method": "credit",
            "customer_id": customer.id,
            "amount_paid": 0,
        })

        def sell():
            return logged_client(vendeur).post(reverse("create_sale"), data=payload, content_type="application/json")

        responses = run_together(sell, sell)

        self.assertEqual(sorted(r.status_code for r in responses), [200, 400])
        refused = next(r for r in responses if r.status_code == 400)
        self.assertIn("Crédit insuffisant", refused.json()["message"])
        customer.refresh_from_db()
        self.assertEqual(customer.current_credit, Decimal("1000"))
        self.assertEqual(Sale.objects.count(), 1)
        medication.refresh_from_db()
        self.assertEqual(medication.quantity, 49)


@unittest.skipUnless(connection.vendor == "postgresql", "concurrence réelle : PostgreSQL requis")
class ConcurrentSaleAndStockMovementTests(TransactionTestCase):
    def test_sale_and_manual_exit_cannot_overdraw(self):
        vendeur = make_user(groups=["Vendeur"])
        pharmacien = make_user(groups=["Pharmacien"])
        medication = make_medication(quantity=30)

        def sell():
            payload = json.dumps({"items": [{"medication_id": medication.id, "quantity": 20}], "payment_method": "carte"})
            return logged_client(vendeur).post(reverse("create_sale"), data=payload, content_type="application/json")

        def record_loss():
            url = reverse("stock_movement_create", args=[medication.pk])
            return logged_client(pharmacien).post(url, {"movement_type": "perte", "quantity": "20"})

        sale_response, loss_response = run_together(sell, record_loss)

        medication.refresh_from_db()
        # Une seule des deux sorties de 20 a pu passer : il reste 10, jamais moins.
        self.assertEqual(medication.quantity, 10)
        self.assertEqual(medication.movements.filter(movement_type__in=["sortie", "perte"]).count(), 1)
        sale_ok = sale_response.status_code == 200
        loss_ok = loss_response.status_code == 302  # redirection vers la fiche après succès
        self.assertTrue(sale_ok != loss_ok, (sale_response.status_code, loss_response.status_code))
        self.assertEqual(Sale.objects.count(), 1 if sale_ok else 0)
