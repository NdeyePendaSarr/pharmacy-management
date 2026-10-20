"""Point 7 : validation des formulaires médicament et catégorie."""
from datetime import timedelta

from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from medications.models import Category, Medication
from pharmanps_alou.testing import make_category, make_medication, make_user

RAW_ERROR_MARKERS = ("IntegrityError", "duplicate key", "violates", "Traceback", "invalid literal", "ValidationError")


class MedicationFormTests(TestCase):
    def setUp(self):
        self.client.force_login(make_user(groups=["Pharmacien"]))
        self.category = make_category()

    def data(self, **overrides):
        values = {
            "name": "Doliprane",
            "dci": "Paracétamol",
            "barcode": "3400000000001",
            "category": self.category.pk,
            "form": "comprimé",
            "dosage": "500mg",
            "purchase_price": "600",
            "selling_price": "1000",
            "quantity": "20",
            "min_quantity": "10",
            "expiry_date": (timezone.localdate() + timedelta(days=365)).isoformat(),
        }
        values.update(overrides)
        return values

    def assert_refused(self, response, expected_text):
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, expected_text)
        for marker in RAW_ERROR_MARKERS:
            self.assertNotContains(response, marker)

    def test_valid_creation_records_initial_stock_as_a_movement(self):
        response = self.client.post(reverse("medication_create"), self.data())
        medication = Medication.objects.get(barcode="3400000000001")
        self.assertRedirects(response, reverse("medication_detail", args=[medication.pk]))
        self.assertEqual(medication.quantity, 20)
        self.assertEqual(list(medication.movements.values_list("movement_type", "quantity")), [("entrée", 20)])

    def test_prices_must_be_positive(self):
        for field in ("purchase_price", "selling_price"):
            for value in ("0", "-5"):
                with self.subTest(field=field, value=value):
                    response = self.client.post(reverse("medication_create"), self.data(**{field: value}))
                    self.assert_refused(response, "supérieur à 0")
        self.assertFalse(Medication.objects.exists())

    def test_selling_price_below_purchase_price_is_refused(self):
        response = self.client.post(reverse("medication_create"), self.data(selling_price="500"))
        self.assert_refused(response, "prix de vente doit être supérieur ou égal au prix d")
        self.assertFalse(Medication.objects.exists())

    def test_quantities_cannot_be_negative(self):
        for field in ("quantity", "min_quantity"):
            with self.subTest(field=field):
                response = self.client.post(reverse("medication_create"), self.data(**{field: "-1"}))
                self.assertEqual(response.status_code, 200)
        self.assertFalse(Medication.objects.exists())

    def test_barcode_is_required_and_unique(self):
        response = self.client.post(reverse("medication_create"), self.data(barcode=""))
        self.assert_refused(response, "Code-barres")
        make_medication(barcode="3400000000001")
        response = self.client.post(reverse("medication_create"), self.data())
        self.assert_refused(response, "existe déjà")
        self.assertEqual(Medication.objects.count(), 1)

    def test_expiry_date_must_be_a_valid_future_date(self):
        for value in ("pas-une-date", "2024-02-31", (timezone.localdate() - timedelta(days=1)).isoformat()):
            with self.subTest(value=value):
                response = self.client.post(reverse("medication_create"), self.data(expiry_date=value))
                self.assertEqual(response.status_code, 200)
                for marker in RAW_ERROR_MARKERS:
                    self.assertNotContains(response, marker)
        self.assertFalse(Medication.objects.exists())

    def test_update_validates_and_keeps_stock(self):
        medication = make_medication(quantity=8)
        url = reverse("medication_update", args=[medication.pk])
        response = self.client.post(url, self.data(barcode=medication.barcode, selling_price="100"))
        self.assert_refused(response, "prix de vente doit être supérieur ou égal au prix d")
        response = self.client.post(url, self.data(barcode=medication.barcode, name="Doliprane 1000", quantity="999"))
        self.assertRedirects(response, reverse("medication_detail", args=[medication.pk]))
        medication.refresh_from_db()
        self.assertEqual(medication.name, "Doliprane 1000")
        self.assertEqual(medication.quantity, 8)

    def test_update_form_shows_quantity_as_read_only(self):
        medication = make_medication(quantity=8)
        response = self.client.get(reverse("medication_update", args=[medication.pk]))
        self.assertNotContains(response, 'name="quantity"')
        self.assertContains(response, "mouvement de stock")


class CategoryFormTests(TestCase):
    def setUp(self):
        self.client.force_login(make_user(groups=["Pharmacien"]))

    def test_name_is_required(self):
        response = self.client.post(reverse("category_create"), {"name": "  "})
        self.assertEqual(response.status_code, 200)
        self.assertFalse(Category.objects.exists())

    def test_duplicate_name_is_refused_without_raw_error(self):
        make_category(name="Antibiotiques")
        for url in (reverse("category_create"), reverse("category_update", args=[make_category().pk])):
            with self.subTest(url=url):
                response = self.client.post(url, {"name": "Antibiotiques"})
                self.assertEqual(response.status_code, 200)
                self.assertContains(response, "existe déjà")
                for marker in RAW_ERROR_MARKERS:
                    self.assertNotContains(response, marker)
        self.assertEqual(Category.objects.filter(name="Antibiotiques").count(), 1)
