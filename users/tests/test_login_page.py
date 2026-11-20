"""
Page de connexion : chaque élément affiché fait ce qu'il annonce.
« Se souvenir de moi » change vraiment la durée de la session, et aucun
lien mort ni badge inexact n'est montré.
"""
from django.conf import settings
from django.test import TestCase
from django.urls import reverse

from pharmanps_alou.testing import make_user

PASSWORD = "x-Test-Pass-123"  # mot de passe des comptes créés par make_user


class RememberMeTests(TestCase):
    def setUp(self):
        self.user = make_user(groups=["Vendeur"])

    def login(self, **extra):
        response = self.client.post(reverse("login"), {"username": self.user.username, "password": PASSWORD, **extra})
        self.assertRedirects(response, reverse("dashboard"))

    def test_without_remember_me_the_session_ends_with_the_browser(self):
        self.login()
        self.assertTrue(self.client.session.get_expire_at_browser_close())

    def test_with_remember_me_the_session_lasts(self):
        self.login(remember="on")
        session = self.client.session
        self.assertFalse(session.get_expire_at_browser_close())
        self.assertEqual(session.get_expiry_age(), settings.SESSION_COOKIE_AGE)


class LoginPageContentTests(TestCase):
    def setUp(self):
        self.html = self.client.get(reverse("login")).content.decode()

    def test_no_dead_link(self):
        self.assertNotIn('href="#"', self.html)
        self.assertIn("Contactez l'administrateur", self.html)

    def test_badges_are_accurate(self):
        self.assertNotIn("Données cryptées", self.html)
        self.assertIn("Mots de passe hachés", self.html)
        self.assertIn('name="remember"', self.html)
