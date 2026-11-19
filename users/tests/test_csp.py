"""
Content-Security-Policy et noms d'hôte : chaque page envoie la politique,
chaque bloc <script> intégré porte le nonce de la requête, aucun attribut
on…="" n'est utilisé, et seuls les CDN autorisés sont appelés.
"""
import re
from html.parser import HTMLParser

from django.conf import settings
from django.test import TestCase
from django.urls import reverse

from pharmanps_alou.testing import make_category, make_customer, make_medication, make_user
from sales import services

ALLOWED_EXTERNAL = ("https://cdn.jsdelivr.net/", "https://cdnjs.cloudflare.com/", "https://fonts.googleapis.com",
                    "https://fonts.gstatic.com")


class _Tags(HTMLParser):
    def __init__(self):
        super().__init__()
        self.scripts, self.handlers, self.external = [], [], []

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == "script":
            self.scripts.append(attrs)
        self.handlers += [f"<{tag} {name}>" for name in attrs if name.startswith("on")]
        for name in ("src", "href"):
            value = attrs.get(name) or ""
            if value.startswith(("http://", "https://")) and tag in ("script", "link"):
                self.external.append(value)


def header_nonce(response):
    policy = response.headers["Content-Security-Policy"]
    match = re.search(r"script-src [^;]*'nonce-([^']+)'", policy)
    return policy, match.group(1) if match else None


class ContentSecurityPolicyTests(TestCase):
    def setUp(self):
        self.client.force_login(make_user(superuser=True))
        self.category = make_category()
        self.medication = make_medication(category=self.category)
        self.customer = make_customer()
        self.sale = services.create_sale(None, {
            "items": [{"medication_id": self.medication.id, "quantity": 1}],
            "payment_method": "carte",
            "customer_id": self.customer.id,
        })

    def pages(self):
        return [
            reverse("dashboard"), reverse("pos"), reverse("medication_list"),
            reverse("medication_create"), reverse("medication_detail", args=[self.medication.pk]),
            reverse("stock_movement_create", args=[self.medication.pk]), reverse("category_list"),
            reverse("sale_list"), reverse("sale_detail", args=[self.sale.pk]),
            reverse("sale_invoice", args=[self.sale.pk]), reverse("customer_list"),
            reverse("customer_detail", args=[self.customer.pk]), reverse("customer_create"),
            reverse("admin:index"), reverse("admin:sales_sale_change", args=[self.sale.pk]),
            reverse("admin:medications_medication_changelist"),
        ]

    def test_policy_is_strict(self):
        policy, nonce = header_nonce(self.client.get(reverse("dashboard")))
        self.assertIsNotNone(nonce)
        directives = dict(part.strip().split(" ", 1) for part in policy.split(";") if part.strip())
        self.assertNotIn("'unsafe-inline'", directives["script-src"])
        self.assertNotIn("'unsafe-eval'", directives["script-src"])
        self.assertEqual(directives["object-src"], "'none'")
        self.assertEqual(directives["frame-ancestors"], "'none'")

    def test_every_inline_script_carries_the_nonce(self):
        for url in self.pages():
            with self.subTest(url=url):
                response = self.client.get(url)
                self.assertEqual(response.status_code, 200)
                _, nonce = header_nonce(response)
                tags = _Tags()
                tags.feed(response.content.decode())
                for script in tags.scripts:
                    if "src" in script or script.get("type") == "application/json":
                        continue
                    self.assertEqual(script.get("nonce"), nonce, f"<script> sans nonce dans {url}")

    def test_no_inline_event_handlers_and_only_allowed_cdns(self):
        for url in self.pages():
            with self.subTest(url=url):
                tags = _Tags()
                tags.feed(self.client.get(url).content.decode())
                self.assertEqual(tags.handlers, [])
                for resource in tags.external:
                    self.assertTrue(resource.startswith(ALLOWED_EXTERNAL), resource)

    def test_cdn_scripts_and_styles_have_integrity(self):
        for url in (reverse("dashboard"),):
            html = self.client.get(url).content.decode()
            for tag in re.findall(r"<(?:script|link)[^>]+(?:cdn\.jsdelivr\.net|cdnjs\.cloudflare\.com)[^>]*>", html):
                self.assertIn('integrity="sha384-', tag)
                self.assertIn('crossorigin="anonymous"', tag)

    def test_login_page_also_has_the_policy(self):
        self.client.logout()
        response = self.client.get(reverse("login"))
        self.assertIn("Content-Security-Policy", response.headers)


class AllowedHostsTests(TestCase):
    def test_no_wildcard_on_render_domain(self):
        self.assertNotIn(".onrender.com", settings.ALLOWED_HOSTS)

    def test_other_render_service_is_refused(self):
        response = self.client.get(reverse("health"), HTTP_HOST="un-autre-service.onrender.com")
        self.assertEqual(response.status_code, 400)
