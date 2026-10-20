"""Point 2 : inscription, rôles Pharmacien / Vendeur, données sensibles, déconnexion."""
import os
from io import StringIO
from unittest import mock

from django.contrib.auth.models import Group, User
from django.core.management import call_command
from django.test import TestCase, override_settings
from django.urls import reverse

from medications.models import Medication
from pharmanps_alou.testing import make_customer, make_medication, make_user


class RegistrationTests(TestCase):
    def test_registration_is_closed_by_default(self):
        response = self.client.post(reverse("register"), {
            "username": "intrus", "email": "intrus@example.com",
            "password": "Un-Mot-De-Passe-Solide-42", "password_confirm": "Un-Mot-De-Passe-Solide-42",
        })
        self.assertEqual(response.status_code, 404)
        self.assertFalse(User.objects.filter(username="intrus").exists())

    def test_login_page_hides_register_link_when_closed(self):
        response = self.client.get(reverse("login"))
        self.assertNotContains(response, reverse("register"))

    @override_settings(ALLOW_REGISTRATION=True)
    def test_registration_can_be_opened_by_setting(self):
        self.assertContains(self.client.get(reverse("login")), reverse("register"))
        response = self.client.post(reverse("register"), {
            "username": "nouvelle", "email": "nouvelle@example.com",
            "password": "Un-Mot-De-Passe-Solide-42", "password_confirm": "Un-Mot-De-Passe-Solide-42",
        })
        self.assertRedirects(response, reverse("login"))
        # Un compte créé par inscription n'a aucun rôle tant qu'un admin ne lui en donne pas.
        self.assertFalse(User.objects.get(username="nouvelle").groups.exists())


class RolePermissionTests(TestCase):
    def setUp(self):
        self.medication = make_medication()
        self.customer = make_customer(
            medical_conditions="Allergie à la pénicilline", date_of_birth="1990-04-12"
        )
        self.vendeur = make_user(groups=["Vendeur"])
        self.pharmacien = make_user(groups=["Pharmacien"])

    def test_both_groups_exist(self):
        self.assertEqual(
            set(Group.objects.filter(name__in=["Pharmacien", "Vendeur"]).values_list("name", flat=True)),
            {"Pharmacien", "Vendeur"},
        )

    def test_vendeur_cannot_modify_or_delete_medication(self):
        self.client.force_login(self.vendeur)
        url_update = reverse("medication_update", args=[self.medication.pk])
        url_delete = reverse("medication_delete", args=[self.medication.pk])
        self.assertEqual(self.client.get(url_update).status_code, 403)
        self.assertEqual(self.client.post(url_update, {"name": "Piraté", "selling_price": "1"}).status_code, 403)
        self.assertEqual(self.client.post(url_delete).status_code, 403)
        self.medication.refresh_from_db()
        self.assertNotEqual(self.medication.name, "Piraté")

    def test_vendeur_cannot_touch_stock_categories_or_customers(self):
        self.client.force_login(self.vendeur)
        forbidden = [
            reverse("medication_create"),
            reverse("stock_movement_create", args=[self.medication.pk]),
            reverse("category_create"),
            reverse("customer_create"),
            reverse("customer_update", args=[self.customer.pk]),
        ]
        for url in forbidden:
            with self.subTest(url=url):
                self.assertEqual(self.client.post(url, {}).status_code, 403)
        self.assertEqual(self.medication.movements.count(), 0)

    def test_vendeur_can_use_till_and_read(self):
        self.client.force_login(self.vendeur)
        allowed = [
            reverse("dashboard"),
            reverse("pos"),
            reverse("sale_list"),
            reverse("medication_list"),
            reverse("medication_detail", args=[self.medication.pk]),
            reverse("customer_list"),
            reverse("customer_detail", args=[self.customer.pk]),
        ]
        for url in allowed:
            with self.subTest(url=url):
                self.assertEqual(self.client.get(url).status_code, 200)

    def test_vendeur_does_not_see_sensitive_customer_data(self):
        self.client.force_login(self.vendeur)
        for url in (reverse("customer_detail", args=[self.customer.pk]), reverse("customer_list")):
            with self.subTest(url=url):
                response = self.client.get(url)
                self.assertNotContains(response, "pénicilline")
                self.assertNotContains(response, "12/04/1990")

    def test_pharmacien_sees_sensitive_customer_data(self):
        self.client.force_login(self.pharmacien)
        response = self.client.get(reverse("customer_detail", args=[self.customer.pk]))
        self.assertContains(response, "pénicilline")
        self.assertContains(response, "12/04/1990")

    def test_pharmacien_can_delete_medication(self):
        self.client.force_login(self.pharmacien)
        response = self.client.post(reverse("medication_delete", args=[self.medication.pk]))
        self.assertRedirects(response, reverse("medication_list"))
        self.assertFalse(Medication.objects.filter(pk=self.medication.pk).exists())

    def test_user_without_role_has_no_access(self):
        self.client.force_login(make_user())
        for url in (reverse("dashboard"), reverse("pos"), reverse("medication_list"), reverse("customer_list")):
            with self.subTest(url=url):
                self.assertEqual(self.client.get(url).status_code, 403)

    def test_anonymous_is_redirected_to_login(self):
        response = self.client.get(reverse("pos"))
        self.assertRedirects(response, f"{reverse('login')}?next={reverse('pos')}")


class LogoutTests(TestCase):
    def setUp(self):
        self.client.force_login(make_user(groups=["Vendeur"]))

    def test_logout_by_get_is_refused(self):
        self.assertEqual(self.client.get(reverse("logout")).status_code, 405)
        self.assertEqual(self.client.get(reverse("pos")).status_code, 200)

    def test_logout_by_post(self):
        self.assertRedirects(self.client.post(reverse("logout")), reverse("login"))
        self.assertEqual(self.client.get(reverse("pos")).status_code, 302)


class DemoAccountCommandTests(TestCase):
    env = {"DEMO_USERNAME": "demo", "DEMO_PASSWORD": "Demo-Vendeur-2026"}

    def run_command(self):
        out = StringIO()
        call_command("init_demo", stdout=out)
        return out.getvalue()

    def test_creates_a_vendeur_account(self):
        with mock.patch.dict(os.environ, self.env):
            self.run_command()
        user = User.objects.get(username="demo")
        self.assertTrue(user.check_password("Demo-Vendeur-2026"))
        self.assertEqual(list(user.groups.values_list("name", flat=True)), ["Vendeur"])
        self.assertFalse(user.is_staff or user.is_superuser)

    def test_is_idempotent(self):
        with mock.patch.dict(os.environ, self.env):
            self.run_command()
            self.run_command()
        self.assertEqual(User.objects.filter(username="demo").count(), 1)
        self.assertEqual(User.objects.get(username="demo").groups.count(), 1)

    def test_skips_without_variables(self):
        with mock.patch.dict(os.environ, {}, clear=True):
            output = self.run_command()
        self.assertIn("ignorée", output)
        self.assertFalse(User.objects.filter(username="demo").exists())
