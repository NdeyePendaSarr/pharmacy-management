"""
Dans l'admin, ventes, lignes de vente et ordonnances sont en consultation
seule, et l'encours de crédit d'un client n'est pas modifiable : seule la
caisse les écrit, avec le stock et le crédit dans la même transaction.
Vérifié avec un superutilisateur, le compte qui a le plus de droits.
"""
from decimal import Decimal

from django.test import TestCase
from django.urls import reverse

from pharmanps_alou.testing import make_customer, make_medication, make_user
from sales import services
from sales.models import Customer, Prescription, Sale, SaleItem


class AdminReadOnlyTests(TestCase):
    def setUp(self):
        self.client.force_login(make_user(superuser=True))
        self.medication = make_medication(requires_prescription=True, quantity=10)
        self.customer = make_customer(credit_limit=Decimal("50000"))
        self.sale = services.create_sale(None, {
            "items": [{"medication_id": self.medication.id, "quantity": 2}],
            "payment_method": "credit",
            "customer_id": self.customer.id,
            "amount_paid": 0,
            "prescription": {"doctor_name": "Dr Fall", "prescription_date": services.oldest_valid_prescription_date().isoformat()},
        })
        self.item = self.sale.items.get()
        self.prescription = Prescription.objects.get()

    def objects(self):
        return {
            "sale": self.sale,
            "saleitem": self.item,
            "prescription": self.prescription,
        }

    def test_list_and_detail_pages_are_viewable(self):
        for model, obj in self.objects().items():
            with self.subTest(model=model):
                self.assertEqual(self.client.get(reverse(f"admin:sales_{model}_changelist")).status_code, 200)
                response = self.client.get(reverse(f"admin:sales_{model}_change", args=[obj.pk]))
                self.assertEqual(response.status_code, 200)
                self.assertFalse(response.context["has_change_permission"])

    def test_add_change_and_delete_are_refused(self):
        for model, obj in self.objects().items():
            with self.subTest(model=model):
                self.assertEqual(self.client.get(reverse(f"admin:sales_{model}_add")).status_code, 403)
                change = self.client.post(reverse(f"admin:sales_{model}_change", args=[obj.pk]), {"quantity": 99})
                self.assertEqual(change.status_code, 403)
                delete = self.client.post(reverse(f"admin:sales_{model}_delete", args=[obj.pk]), {"post": "yes"})
                self.assertEqual(delete.status_code, 403)

        self.assertEqual(Sale.objects.count(), 1)
        self.assertEqual(SaleItem.objects.get().quantity, 2)
        self.assertEqual(Prescription.objects.count(), 1)

    def test_bulk_delete_action_is_not_offered(self):
        response = self.client.get(reverse("admin:sales_sale_changelist"))
        self.assertNotContains(response, "delete_selected")

    def test_customer_credit_cannot_be_edited(self):
        self.customer.refresh_from_db()
        self.assertEqual(self.customer.current_credit, self.sale.total)

        url = reverse("admin:sales_customer_change", args=[self.customer.pk])
        form = self.client.get(url).context["adminform"].form
        self.assertNotIn("current_credit", form.fields)

        data = {
            "first_name": self.customer.first_name,
            "last_name": self.customer.last_name,
            "phone": self.customer.phone,
            "customer_type": self.customer.customer_type,
            "loyalty_points": 0,
            "credit_limit": "60000",
            "current_credit": "0",
        }
        response = self.client.post(url, data)
        self.assertEqual(response.status_code, 302)
        customer = Customer.objects.get(pk=self.customer.pk)
        self.assertEqual(customer.credit_limit, Decimal("60000"))
        self.assertEqual(customer.current_credit, self.sale.total)
