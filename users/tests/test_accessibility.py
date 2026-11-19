"""
Accessibilité de base : chaque champ de formulaire a un libellé associé,
la caisse annonce ses messages dans la page (plus d'alert()), et le menu
ne montre que les liens autorisés pour le rôle.
"""
import re
from html.parser import HTMLParser

from django.contrib.auth.models import Permission
from django.test import TestCase
from django.urls import reverse

from pharmanps_alou.testing import make_category, make_customer, make_medication, make_user


class _Fields(HTMLParser):
    """Champs visibles et moyens de les nommer (label for=, label englobant, aria-label)."""

    def __init__(self):
        super().__init__()
        self.fields, self.label_for, self.open_labels = [], set(), 0

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == "label":
            self.open_labels += 1
            if attrs.get("for"):
                self.label_for.add(attrs["for"])
        elif tag in ("input", "select", "textarea"):
            if attrs.get("type") in ("hidden", "submit", "button"):
                return
            self.fields.append((tag, attrs, self.open_labels > 0))

    def handle_endtag(self, tag):
        if tag == "label":
            self.open_labels -= 1

    def unlabelled(self):
        return [
            f"<{tag} name={attrs.get('name')} id={attrs.get('id')}>"
            for tag, attrs, wrapped in self.fields
            if not (wrapped or attrs.get("aria-label") or attrs.get("id") in self.label_for)
        ]


class FormLabelTests(TestCase):
    def setUp(self):
        self.client.force_login(make_user(groups=["Pharmacien"]))
        self.medication = make_medication()
        self.category = make_category()
        self.customer = make_customer()

    def test_every_field_has_a_label(self):
        pages = [
            reverse("medication_create"), reverse("medication_update", args=[self.medication.pk]),
            reverse("category_create"), reverse("category_update", args=[self.category.pk]),
            reverse("stock_movement_create", args=[self.medication.pk]),
            reverse("customer_create"), reverse("customer_update", args=[self.customer.pk]),
            reverse("medication_list"), reverse("customer_list"), reverse("sale_list"), reverse("pos"),
        ]
        for url in pages:
            with self.subTest(url=url):
                parser = _Fields()
                parser.feed(self.client.get(url).content.decode())
                self.assertTrue(parser.fields, "aucun champ trouvé")
                self.assertEqual(parser.unlabelled(), [])


class PosMessageTests(TestCase):
    def setUp(self):
        self.client.force_login(make_user(groups=["Vendeur"]))
        self.html = self.client.get(reverse("pos")).content.decode()

    def test_till_uses_a_live_region_instead_of_alerts(self):
        self.assertIn('id="posMessage"', self.html)
        self.assertIn('aria-live="polite"', self.html)
        self.assertIsNone(re.search(r"alert\(['`]", self.html), "la caisse appelle encore alert()")
        self.assertNotIn("window.open(", self.html)

    def test_payment_buttons_expose_their_state(self):
        self.assertEqual(self.html.count('aria-pressed="true"'), 1)
        self.assertEqual(self.html.count('aria-pressed="false"'), 3)
        self.assertIn('role="group" aria-labelledby="paymentMethodLabel"', self.html)


class NavigationByRoleTests(TestCase):
    def nav_links(self, user):
        self.client.force_login(user)
        html = self.client.get(reverse("medication_list")).content.decode()
        return set(re.findall(r'href="(/(?:dashboard|medications|sales|customers|pos)/)"', html))

    def test_vendeur_sees_every_section_of_the_till(self):
        links = self.nav_links(make_user(groups=["Vendeur"]))
        self.assertEqual(links, {"/dashboard/", "/medications/", "/sales/", "/customers/", "/pos/"})

    def test_links_follow_permissions(self):
        user = make_user()
        user.user_permissions.add(Permission.objects.get(codename="view_medication"))
        links = self.nav_links(user)
        self.assertIn("/medications/", links)
        self.assertNotIn("/pos/", links)
        self.assertNotIn("/sales/", links)
        self.assertNotIn("/dashboard/", links)

    def test_mobile_menu_button_is_labelled(self):
        self.client.force_login(make_user(groups=["Vendeur"]))
        html = self.client.get(reverse("pos")).content.decode()
        self.assertIn('aria-label="Menu de navigation"', html)
