"""
Un même panier envoyé deux fois (double clic, relance après une coupure
réseau) ne crée qu'une vente : le jeton de la caisse la retrouve.
"""
import json
import threading
import unittest
import uuid

from django.db import connection
from django.test import Client, TestCase, TransactionTestCase
from django.urls import reverse

from pharmanps_alou.testing import make_medication, make_user
from sales import services
from sales.models import Sale


def post_sale(client, medication, token, quantity=1):
    payload = {
        "items": [{"medication_id": medication.id, "quantity": quantity}],
        "payment_method": "carte",
        "client_token": token,
    }
    return client.post(reverse("create_sale"), data=json.dumps(payload), content_type="application/json")


class DoubleSubmitTests(TestCase):
    def setUp(self):
        self.user = make_user(groups=["Vendeur"])
        self.client.force_login(self.user)
        self.medication = make_medication(quantity=10)

    def test_same_token_creates_a_single_sale(self):
        token = str(uuid.uuid4())
        first = post_sale(self.client, self.medication, token)
        second = post_sale(self.client, self.medication, token)

        self.assertEqual((first.status_code, second.status_code), (200, 200))
        self.assertEqual(first.json()["sale_id"], second.json()["sale_id"])
        self.assertEqual(Sale.objects.count(), 1)
        self.medication.refresh_from_db()
        self.assertEqual(self.medication.quantity, 9)
        self.assertEqual(self.medication.movements.filter(movement_type="sortie").count(), 1)

    def test_new_token_creates_a_new_sale(self):
        post_sale(self.client, self.medication, str(uuid.uuid4()))
        post_sale(self.client, self.medication, str(uuid.uuid4()))
        self.assertEqual(Sale.objects.count(), 2)

    def test_replay_succeeds_even_when_stock_is_now_insufficient(self):
        # Le premier envoi a pris tout le stock : le second doit renvoyer la
        # vente, pas une erreur « stock insuffisant ».
        token = str(uuid.uuid4())
        post_sale(self.client, self.medication, token, quantity=10)
        replay = post_sale(self.client, self.medication, token, quantity=10)
        self.assertEqual(replay.status_code, 200, replay.content)
        self.assertEqual(Sale.objects.count(), 1)

    def test_malformed_token_is_refused(self):
        response = post_sale(self.client, self.medication, "pas-un-uuid")
        self.assertEqual(response.status_code, 400)
        self.assertFalse(Sale.objects.exists())

    def test_token_of_another_user_is_refused(self):
        token = str(uuid.uuid4())
        post_sale(self.client, self.medication, token)
        other = Client()
        other.force_login(make_user(groups=["Vendeur"]))
        response = post_sale(other, self.medication, token)
        self.assertEqual(response.status_code, 400)
        self.assertNotIn("sale_id", response.json())
        self.assertEqual(Sale.objects.count(), 1)

    def test_sale_without_token_still_works(self):
        # Ventes créées hors caisse (seed_data) : pas de jeton.
        services.create_sale(self.user, {
            "items": [{"medication_id": self.medication.id, "quantity": 1}],
            "payment_method": "carte",
        })
        services.create_sale(self.user, {
            "items": [{"medication_id": self.medication.id, "quantity": 1}],
            "payment_method": "carte",
        })
        self.assertEqual(Sale.objects.filter(client_token__isnull=True).count(), 2)

    def test_till_sends_a_token_and_blocks_double_clicks(self):
        html = self.client.get(reverse("pos")).content.decode()
        self.assertIn("client_token: saleToken", html)
        self.assertIn("completeBtn.disabled = true", html)


@unittest.skipUnless(connection.vendor == "postgresql", "concurrence réelle : PostgreSQL requis")
class ConcurrentDoubleSubmitTests(TransactionTestCase):
    def test_simultaneous_requests_with_same_token_create_one_sale(self):
        user = make_user(groups=["Vendeur"])
        medication = make_medication(quantity=10)
        token = str(uuid.uuid4())
        barrier = threading.Barrier(2)
        responses = []

        def worker():
            client = Client()
            client.force_login(user)
            barrier.wait()
            try:
                responses.append(post_sale(client, medication, token))
            finally:
                connection.close()

        threads = [threading.Thread(target=worker) for _ in range(2)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()

        self.assertEqual([r.status_code for r in responses], [200, 200])
        self.assertEqual(len({r.json()["sale_id"] for r in responses}), 1)
        self.assertEqual(Sale.objects.count(), 1)
        medication.refresh_from_db()
        self.assertEqual(medication.quantity, 9)
