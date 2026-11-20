"""
Migration 0006 (archivage des clients, PROTECT) : appliquée sur des données
existantes, elle ne perd rien et rend tous les clients actifs ; elle se
défait sans perte non plus.
"""
from datetime import date
from decimal import Decimal

from django.db import connection
from django.db.migrations.executor import MigrationExecutor
from django.test import TransactionTestCase

BEFORE = [("sales", "0005_sale_client_token"), ("medications", "0004_stock_constraints")]
AFTER = [("sales", "0006_customer_archive_protect_history")]


class Migration0006Tests(TransactionTestCase):
    def migrate(self, targets):
        executor = MigrationExecutor(connection)
        executor.loader.build_graph()
        executor.migrate(targets)
        return executor.loader.project_state(targets).apps

    def tearDown(self):
        # Remet la base au dernier état pour les tests suivants.
        executor = MigrationExecutor(connection)
        executor.migrate(executor.loader.graph.leaf_nodes())

    def test_forward_and_backward_keep_all_data(self):
        apps = self.migrate(BEFORE)
        Customer = apps.get_model("sales", "Customer")
        Sale = apps.get_model("sales", "Sale")
        Prescription = apps.get_model("sales", "Prescription")
        customer = Customer.objects.create(
            first_name="Awa", last_name="Diop", phone="770000000", current_credit=Decimal("1500")
        )
        sale = Sale.objects.create(sale_number="V-MIG-1", customer=customer, payment_method="credit",
                                   status="completee", total=Decimal("1500"))
        Prescription.objects.create(customer=customer, sale=sale, doctor_name="Dr Fall",
                                    prescription_date=date(2026, 11, 1))

        apps = self.migrate(AFTER)
        Customer = apps.get_model("sales", "Customer")
        migrated = Customer.objects.get(pk=customer.pk)
        self.assertTrue(migrated.is_active)
        self.assertIsNone(migrated.archived_at)
        self.assertEqual(migrated.current_credit, Decimal("1500"))
        self.assertEqual(apps.get_model("sales", "Sale").objects.get().customer_id, customer.pk)
        self.assertEqual(apps.get_model("sales", "Prescription").objects.get().customer_id, customer.pk)

        apps = self.migrate(BEFORE)
        Customer = apps.get_model("sales", "Customer")
        self.assertEqual(Customer.objects.get(pk=customer.pk).current_credit, Decimal("1500"))
        self.assertEqual(apps.get_model("sales", "Prescription").objects.count(), 1)
        self.assertEqual(apps.get_model("sales", "Sale").objects.count(), 1)
