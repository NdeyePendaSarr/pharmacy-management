"""Point 5 : le stock ne change que par des mouvements positifs, atomiques et tracés."""
import json
import threading
import unittest
from datetime import timedelta

from django.db import connection
from django.test import Client, TestCase, TransactionTestCase
from django.urls import reverse
from django.utils import timezone

from medications.models import Medication, StockMovement
from pharmanps_alou.testing import make_medication, make_user


def signed_total(medication):
    """Somme des mouvements avec leur sens : doit toujours égaler le stock."""
    total = 0
    for movement in medication.movements.all():
        if movement.movement_type in StockMovement.INBOUND_TYPES:
            total += movement.quantity
        else:
            total -= movement.quantity
    return total


class StockMovementViewTests(TestCase):
    def setUp(self):
        self.client.force_login(make_user(groups=["Pharmacien"]))
        self.medication = make_medication(quantity=0)
        self.url = reverse("stock_movement_create", args=[self.medication.pk])

    def post_movement(self, movement_type, quantity):
        return self.client.post(self.url, {"movement_type": movement_type, "quantity": quantity})

    def test_outgoing_movement_above_stock_is_refused(self):
        self.post_movement("entrée", 10)
        response = self.post_movement("sortie", 11)
        self.assertEqual(response.status_code, 200)  # formulaire réaffiché avec l'erreur
        self.assertContains(response, "Stock insuffisant")
        self.medication.refresh_from_db()
        self.assertEqual(self.medication.quantity, 10)
        self.assertEqual(self.medication.movements.count(), 1)

    def test_quantity_must_be_positive(self):
        for quantity in (0, -5):
            with self.subTest(quantity=quantity):
                self.post_movement("entrée", quantity)
        self.medication.refresh_from_db()
        self.assertEqual(self.medication.quantity, 0)
        self.assertFalse(self.medication.movements.exists())

    def test_adjustment_can_go_up_or_down(self):
        self.post_movement("entrée", 20)
        self.post_movement("ajustement_plus", 5)
        self.post_movement("ajustement_moins", 8)
        self.medication.refresh_from_db()
        self.assertEqual(self.medication.quantity, 17)
        response = self.post_movement("ajustement_moins", 18)
        self.assertContains(response, "Stock insuffisant")
        self.medication.refresh_from_db()
        self.assertEqual(self.medication.quantity, 17)

    def test_history_reflects_every_change(self):
        for movement_type, quantity in [("entrée", 30), ("perte", 2), ("retour", 1), ("périmé", 4), ("ajustement_moins", 3)]:
            self.post_movement(movement_type, quantity)
        self.medication.refresh_from_db()
        self.assertEqual(self.medication.quantity, 22)
        self.assertEqual(self.medication.movements.count(), 5)
        self.assertEqual(signed_total(self.medication), self.medication.quantity)

    def test_sale_is_recorded_as_an_outgoing_movement(self):
        self.post_movement("entrée", 10)
        response = self.client.post(
            reverse("create_sale"),
            data=json.dumps({"items": [{"medication_id": self.medication.id, "quantity": 3}], "payment_method": "carte"}),
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 200, response.content)
        sale_movement = self.medication.movements.get(movement_type="sortie")
        self.assertEqual(sale_movement.quantity, 3)
        self.assertEqual(sale_movement.reference, response.json()["sale_number"])
        self.medication.refresh_from_db()
        self.assertEqual(self.medication.quantity, 7)
        self.assertEqual(signed_total(self.medication), 7)


class MedicationUpdateStockTests(TestCase):
    def test_update_form_cannot_change_quantity(self):
        self.client.force_login(make_user(groups=["Pharmacien"]))
        medication = make_medication(quantity=12)
        response = self.client.post(reverse("medication_update", args=[medication.pk]), {
            "name": medication.name,
            "dci": medication.dci,
            "barcode": medication.barcode,
            "form": medication.form,
            "dosage": medication.dosage,
            "purchase_price": "600",
            "selling_price": "1000",
            "quantity": "999",
            "min_quantity": "10",
            "expiry_date": (timezone.localdate() + timedelta(days=200)).isoformat(),
        })
        self.assertRedirects(response, reverse("medication_detail", args=[medication.pk]))
        medication.refresh_from_db()
        self.assertEqual(medication.quantity, 12)


@unittest.skipUnless(connection.vendor == "postgresql", "verrouillage SELECT ... FOR UPDATE : PostgreSQL requis")
class ConcurrentStockTests(TransactionTestCase):
    """Deux opérations simultanées ne doivent jamais faire passer le stock sous zéro."""

    def setUp(self):
        self.user = make_user(groups=["Pharmacien"])
        self.medication = make_medication(quantity=50)

    def run_concurrently(self, send):
        barrier = threading.Barrier(2)
        responses = []

        def worker():
            client = Client()
            client.force_login(self.user)
            barrier.wait()
            try:
                responses.append(send(client))
            finally:
                connection.close()

        threads = [threading.Thread(target=worker) for _ in range(2)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()
        return responses

    def test_two_sales_cannot_oversell(self):
        payload = json.dumps({
            "items": [{"medication_id": self.medication.id, "quantity": 30}],
            "payment_method": "carte",
        })
        responses = self.run_concurrently(
            lambda client: client.post(reverse("create_sale"), data=payload, content_type="application/json")
        )
        self.assertEqual(sorted(r.status_code for r in responses), [200, 400])
        self.medication.refresh_from_db()
        self.assertEqual(self.medication.quantity, 20)
        self.assertEqual(self.medication.movements.filter(movement_type="sortie").count(), 1)

    def test_two_stock_exits_cannot_overdraw(self):
        url = reverse("stock_movement_create", args=[self.medication.pk])
        self.run_concurrently(lambda client: client.post(url, {"movement_type": "perte", "quantity": 30}))
        self.medication.refresh_from_db()
        self.assertEqual(self.medication.quantity, 20)
        self.assertEqual(self.medication.movements.count(), 1)
        self.assertEqual(Medication.objects.get(pk=self.medication.pk).quantity, 50 - 30)
