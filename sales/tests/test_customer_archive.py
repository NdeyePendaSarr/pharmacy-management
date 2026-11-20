"""
Aucune suppression de client ne fait disparaître ses ordonnances, ses ventes
ou son encours de crédit. Un client avec un historique s'archive : il est
masqué de la liste et de la caisse, et tout reste consultable.
"""
from decimal import Decimal

from django.db.models import ProtectedError
from django.test import TestCase
from django.urls import reverse

from pharmanps_alou.testing import make_customer, make_medication, make_user
from sales import services
from sales.models import Customer, Prescription, Sale


def sell(customer, *, payment_method="credit", prescription=False):
    medication = make_medication(requires_prescription=prescription, selling_price=Decimal("1000"))
    data = {
        "items": [{"medication_id": medication.id, "quantity": 2}],
        "payment_method": payment_method,
        "customer_id": customer.id,
        "amount_paid": 0,
    }
    if prescription:
        data["prescription"] = {
            "doctor_name": "Dr Fall",
            "prescription_date": services.oldest_valid_prescription_date().isoformat(),
        }
    return services.create_sale(None, data)


class DeletionProtectionTests(TestCase):
    """Le code (shell, futur développement) ne peut rien effacer non plus."""

    def test_deleting_a_customer_keeps_prescriptions(self):
        # Reproduit le problème d'origine : l'ordonnance disparaissait (CASCADE).
        customer = make_customer(credit_limit=Decimal("50000"))
        sell(customer, prescription=True)
        with self.assertRaises(ProtectedError):
            customer.delete()
        self.assertTrue(Customer.objects.filter(pk=customer.pk).exists())
        self.assertEqual(Prescription.objects.get().customer, customer)

    def test_deleting_a_customer_keeps_the_link_on_sales(self):
        # Auparavant SET_NULL : la vente perdait son client.
        customer = make_customer()
        sale = sell(customer, payment_method="carte")
        with self.assertRaises(ProtectedError):
            customer.delete()
        sale.refresh_from_db()
        self.assertEqual(sale.customer, customer)


class AdminDeletionTests(TestCase):
    def setUp(self):
        self.client.force_login(make_user(superuser=True))

    def delete(self, customer):
        return self.client.post(
            reverse("admin:sales_customer_delete", args=[customer.pk]), {"post": "yes"}, follow=True
        )

    def test_customer_with_credit_is_not_deleted(self):
        customer = make_customer(credit_limit=Decimal("50000"))
        sell(customer)
        response = self.delete(customer)

        customer.refresh_from_db()
        self.assertEqual(customer.current_credit, Decimal("2000"))
        self.assertEqual(Sale.objects.get().customer, customer)
        self.assertContains(response, "Impossible de supprimer")
        self.assertContains(response, "1 vente(s)")
        self.assertContains(response, "un encours de crédit de 2000 FCFA")
        self.assertContains(response, "Archiver")

    def test_customer_with_prescription_gets_a_clear_message(self):
        # Avant : erreur 403 sans explication.
        customer = make_customer(credit_limit=Decimal("50000"))
        sell(customer, payment_method="carte", prescription=True)
        response = self.delete(customer)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "1 ordonnance(s)")
        self.assertEqual(Prescription.objects.count(), 1)
        self.assertTrue(Customer.objects.filter(pk=customer.pk).exists())

    def test_customer_with_sales_but_no_debt_is_not_deleted(self):
        customer = make_customer()
        sell(customer, payment_method="carte")
        response = self.delete(customer)
        self.assertContains(response, "1 vente(s)")
        self.assertNotContains(response, "encours de crédit")
        self.assertTrue(Customer.objects.filter(pk=customer.pk).exists())

    def test_customer_without_history_can_be_deleted(self):
        # Fiche créée par erreur : rien d'autre ne disparaît avec elle.
        customer = make_customer()
        self.assertEqual(customer.deletion_blockers(), [])
        response = self.delete(customer)
        self.assertEqual(response.status_code, 200)
        self.assertFalse(Customer.objects.filter(pk=customer.pk).exists())

    def test_bulk_delete_is_not_offered(self):
        make_customer()  # la barre d'actions n'apparaît qu'avec au moins un client
        response = self.client.get(reverse("admin:sales_customer_changelist"))
        self.assertNotContains(response, "delete_selected")
        self.assertContains(response, "archive_customers")


class ArchiveTests(TestCase):
    def setUp(self):
        self.admin = make_user(superuser=True)
        self.client.force_login(self.admin)
        self.customer = make_customer(last_name="Archivable", credit_limit=Decimal("50000"))
        self.sale = sell(self.customer, prescription=True)

    def run_action(self, action):
        return self.client.post(
            reverse("admin:sales_customer_changelist"),
            {"action": action, "_selected_action": [self.customer.pk]},
            follow=True,
        )

    def test_archiving_hides_the_customer_and_keeps_history(self):
        response = self.run_action("archive_customers")
        self.assertContains(response, "1 client(s) archivé(s)")

        self.customer.refresh_from_db()
        self.assertFalse(self.customer.is_active)
        self.assertIsNotNone(self.customer.archived_at)
        # Historique intact.
        self.assertEqual(self.customer.current_credit, Decimal("2000"))
        self.assertEqual(Sale.objects.get().customer, self.customer)
        self.assertEqual(Prescription.objects.get().customer, self.customer)

        vendeur = make_user(groups=["Vendeur"])
        self.client.force_login(vendeur)
        # Masqué de la liste et de la caisse…
        self.assertNotIn(self.customer, self.client.get(reverse("customer_list")).context["customers"])
        found = self.client.get(reverse("search_customer"), {"q": "Archivable"}).json()["results"]
        self.assertEqual(found, [])
        # …mais sa fiche et ses ventes restent consultables.
        detail = self.client.get(reverse("customer_detail", args=[self.customer.pk]))
        self.assertContains(detail, "Client archivé le")
        self.assertEqual(len(self.client.get(reverse("customer_sales", args=[self.customer.pk])).context["sales"]), 1)
        self.assertEqual(self.client.get(reverse("sale_invoice", args=[self.sale.pk])).status_code, 200)

    def test_archived_customer_cannot_buy(self):
        self.run_action("archive_customers")
        with self.assertRaisesMessage(services.SaleError, "est archivé"):
            sell(self.customer, payment_method="carte")
        self.assertEqual(Sale.objects.count(), 1)

    def test_reactivation(self):
        self.run_action("archive_customers")
        response = self.run_action("reactivate_customers")
        self.assertContains(response, "1 client(s) réactivé(s)")
        self.customer.refresh_from_db()
        self.assertTrue(self.customer.is_active)
        self.assertIsNone(self.customer.archived_at)
        sell(self.customer, payment_method="carte")
        self.assertEqual(Sale.objects.count(), 2)

    def test_archive_status_is_not_editable_by_hand(self):
        form = self.client.get(reverse("admin:sales_customer_change", args=[self.customer.pk])).context["adminform"].form
        self.assertNotIn("is_active", form.fields)
        self.assertNotIn("archived_at", form.fields)

    def test_vendeur_cannot_archive(self):
        # Les actions exigent la permission de modifier un client (Pharmacien).
        vendeur = make_user(groups=["Vendeur"])
        vendeur.is_staff = True
        vendeur.save()
        self.client.force_login(vendeur)
        self.client.post(
            reverse("admin:sales_customer_changelist"),
            {"action": "archive_customers", "_selected_action": [self.customer.pk]},
        )
        self.customer.refresh_from_db()
        self.assertTrue(self.customer.is_active)
