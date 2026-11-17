"""
Commandes lancées par build.sh sur une base neuve (changement de base
PostgreSQL) : elles doivent reconstruire une démo complète, sans doublon
lorsqu'elles sont relancées à chaque déploiement.
"""
import os
from io import StringIO
from unittest import mock

from django.contrib.auth.models import User
from django.core.management import call_command
from django.test import TestCase

from medications.models import Category, Medication, StockMovement
from sales.models import Customer, Prescription, Sale


def run(command, env=None):
    out = StringIO()
    with mock.patch.dict(os.environ, env or {}, clear=env is None):
        call_command(command, stdout=out)
    return out.getvalue()


class InitAdminCommandTests(TestCase):
    env = {"ADMIN_USERNAME": "admin", "ADMIN_EMAIL": "admin@example.com", "ADMIN_PASSWORD": "Admin-Test-Pass-2026"}

    def test_creates_the_superuser(self):
        run("init_admin", self.env)
        user = User.objects.get(username="admin")
        self.assertTrue(user.is_superuser and user.is_staff)
        self.assertTrue(user.check_password("Admin-Test-Pass-2026"))
        self.assertEqual(user.email, "admin@example.com")

    def test_is_idempotent(self):
        run("init_admin", self.env)
        output = run("init_admin", self.env)
        self.assertIn("existe déjà", output)
        self.assertEqual(User.objects.filter(username="admin").count(), 1)

    def test_skips_without_variables(self):
        output = run("init_admin")
        self.assertIn("ignorée", output)
        self.assertFalse(User.objects.exists())


class SeedDataCommandTests(TestCase):
    def test_fills_an_empty_database(self):
        run("init_admin", InitAdminCommandTests.env)
        run("seed_data", {})

        self.assertEqual(Category.objects.count(), 10)
        self.assertEqual(Medication.objects.count(), 18)
        self.assertEqual(Customer.objects.count(), 6)
        self.assertEqual(Sale.objects.filter(status="completee").count(), 3)
        self.assertEqual(Prescription.objects.count(), 2)

        # Le stock est cohérent avec l'historique des mouvements.
        for medication in Medication.objects.all():
            history = sum(m.signed_quantity for m in medication.movements.all())
            self.assertEqual(medication.quantity, history, medication.name)
        self.assertEqual(StockMovement.objects.filter(movement_type="sortie").count(), 6)

    def test_does_nothing_when_medications_exist(self):
        run("seed_data", {})
        output = run("seed_data", {})
        self.assertIn("remplissage ignoré", output)
        self.assertEqual(Medication.objects.count(), 18)
        self.assertEqual(Sale.objects.count(), 3)
