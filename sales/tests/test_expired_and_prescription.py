"""Point 4 : médicaments périmés exclus de la caisse ; ordonnance exigée quand elle est requise."""
import json
from datetime import timedelta

from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from pharmanps_alou.testing import make_customer, make_medication, make_user
from sales.models import Prescription, Sale


def post_sale(client, **payload):
    payload.setdefault("payment_method", "carte")
    return client.post(reverse("create_sale"), data=json.dumps(payload), content_type="application/json")


class ExpiredMedicationTests(TestCase):
    def setUp(self):
        self.client.force_login(make_user(groups=["Vendeur"]))
        today = timezone.localdate()
        self.expired = make_medication(name="Amoxicilline périmée", expiry_date=today - timedelta(days=1))
        self.last_day = make_medication(name="Amoxicilline dernier jour", expiry_date=today)

    def test_pos_does_not_list_expired_medications(self):
        response = self.client.get(reverse("pos"))
        self.assertNotContains(response, "Amoxicilline périmée")
        self.assertContains(response, "Amoxicilline dernier jour")

    def test_search_does_not_return_expired_medications(self):
        response = self.client.get(reverse("search_medication"), {"q": "Amoxicilline"})
        names = [result["name"] for result in response.json()["results"]]
        self.assertEqual(names, ["Amoxicilline dernier jour"])

    def test_sale_of_expired_medication_is_refused(self):
        response = post_sale(self.client, items=[{"medication_id": self.expired.id, "quantity": 1}])
        self.assertEqual(response.status_code, 400)
        self.assertIn("périmé", response.json()["message"])
        self.assertFalse(Sale.objects.exists())
        self.expired.refresh_from_db()
        self.assertEqual(self.expired.quantity, 50)

    def test_medication_is_sellable_until_its_expiry_date(self):
        response = post_sale(self.client, items=[{"medication_id": self.last_day.id, "quantity": 1}])
        self.assertEqual(response.status_code, 200, response.content)


class PrescriptionRuleTests(TestCase):
    def setUp(self):
        self.client.force_login(make_user(groups=["Vendeur"]))
        self.antibiotic = make_medication(name="Augmentin", requires_prescription=True)
        self.customer = make_customer()
        self.today = timezone.localdate()

    def prescription(self, **overrides):
        values = {"doctor_name": "Dr Ndiaye", "prescription_date": self.today.isoformat()}
        values.update(overrides)
        return values

    def test_prescription_medication_requires_a_customer(self):
        response = post_sale(
            self.client,
            items=[{"medication_id": self.antibiotic.id, "quantity": 1}],
            prescription=self.prescription(),
        )
        self.assertEqual(response.status_code, 400)
        self.assertIn("client", response.json()["message"].lower())
        self.assertFalse(Sale.objects.exists())

    def test_prescription_medication_requires_a_prescription(self):
        response = post_sale(
            self.client, items=[{"medication_id": self.antibiotic.id, "quantity": 1}], customer_id=self.customer.id
        )
        self.assertEqual(response.status_code, 400)
        self.assertIn("ordonnance", response.json()["message"].lower())
        self.assertFalse(Sale.objects.exists())

    def test_prescription_must_be_complete_and_not_in_the_future(self):
        invalid = [
            self.prescription(doctor_name="  "),
            self.prescription(prescription_date="pas-une-date"),
            self.prescription(prescription_date=(self.today + timedelta(days=1)).isoformat()),
        ]
        for prescription in invalid:
            with self.subTest(prescription=prescription):
                response = post_sale(
                    self.client,
                    items=[{"medication_id": self.antibiotic.id, "quantity": 1}],
                    customer_id=self.customer.id,
                    prescription=prescription,
                )
                self.assertEqual(response.status_code, 400)
        self.assertFalse(Sale.objects.exists())

    def test_sale_with_prescription_links_it_to_the_sale(self):
        response = post_sale(
            self.client,
            items=[{"medication_id": self.antibiotic.id, "quantity": 1}],
            customer_id=self.customer.id,
            prescription=self.prescription(),
        )
        self.assertEqual(response.status_code, 200, response.content)
        sale = Sale.objects.get()
        prescription = Prescription.objects.get()
        self.assertEqual(prescription.sale, sale)
        self.assertEqual(prescription.customer, self.customer)
        self.assertEqual(prescription.doctor_name, "Dr Ndiaye")

    def test_over_the_counter_sale_needs_no_prescription(self):
        paracetamol = make_medication(requires_prescription=False)
        response = post_sale(self.client, items=[{"medication_id": paracetamol.id, "quantity": 1}])
        self.assertEqual(response.status_code, 200, response.content)
        self.assertFalse(Prescription.objects.exists())
