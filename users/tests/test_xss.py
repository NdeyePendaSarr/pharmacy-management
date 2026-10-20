"""Point 3 : un nom de médicament piégé reste du texte, jamais du code exécuté."""
from django.test import TestCase
from django.urls import reverse

from pharmanps_alou.testing import make_medication, make_user
from sales import services

PAYLOAD = "</script><script>alert(1)</script>"


class DashboardXssTests(TestCase):
    def setUp(self):
        self.client.force_login(make_user(superuser=True))
        med = make_medication(name=PAYLOAD)
        # Le médicament doit avoir été vendu pour apparaître dans le graphique « top 5 ».
        services.create_sale(None, {
            "items": [{"medication_id": med.id, "quantity": 1}],
            "payment_method": "carte",
        })

    def test_medication_name_is_rendered_as_text(self):
        html = self.client.get(reverse("dashboard")).content.decode()
        self.assertFalse(PAYLOAD in html, "le nom piégé apparaît brut dans le tableau de bord")
        self.assertFalse("<script>alert(1)" in html, "une balise <script> injectée est présente")
        # Les données passent par json_script : les chevrons sont échappés en \u003C.
        self.assertIn('id="chart-products-labels"', html)
        self.assertIn("\\u003C/script\\u003E\\u003Cscript\\u003Ealert(1)", html)


class PosXssTests(TestCase):
    def setUp(self):
        self.client.force_login(make_user(superuser=True))
        make_medication(name=PAYLOAD)

    def test_pos_page_escapes_medication_name(self):
        html = self.client.get(reverse("pos")).content.decode()
        self.assertFalse(PAYLOAD in html, "le nom piégé apparaît brut dans la caisse")

    def test_pos_script_never_injects_html(self):
        # Les résultats de recherche et le panier sont construits avec
        # createElement / textContent : aucun innerHTML dans la page.
        html = self.client.get(reverse("pos")).content.decode()
        self.assertFalse("innerHTML" in html, "la caisse utilise encore innerHTML")
        self.assertFalse("onclick=" in html, "la caisse utilise encore des gestionnaires onclick en ligne")
