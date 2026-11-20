"""
Caisse : les clients sont cherchés à la demande (nom, prénom ou téléphone)
au lieu d'être tous chargés dans la page.
"""
from django.db import connection
from django.test import TestCase
from django.test.utils import CaptureQueriesContext
from django.urls import reverse

from pharmanps_alou.testing import make_customer, make_user
from sales.views import CUSTOMER_SEARCH_LIMIT


class CustomerSearchApiTests(TestCase):
    def setUp(self):
        self.client.force_login(make_user(groups=["Vendeur"]))

    def search(self, query):
        response = self.client.get(reverse("search_customer"), {"q": query})
        self.assertEqual(response.status_code, 200)
        return response.json()["results"]

    def test_finds_by_last_name_first_name_or_phone(self):
        awa = make_customer(first_name="Awa", last_name="Ndiaye", phone="771234567")
        make_customer(first_name="Moussa", last_name="Fall", phone="701111111")
        expected = [{"id": awa.id, "name": "Awa Ndiaye", "phone": "771234567"}]
        self.assertEqual(self.search("ndia"), expected)
        self.assertEqual(self.search("AWA"), expected)
        self.assertEqual(self.search("12345"), expected)

    def test_short_query_returns_nothing(self):
        make_customer(last_name="Ba")
        self.assertEqual(self.search(""), [])
        self.assertEqual(self.search("B"), [])
        self.assertEqual(self.search(" B "), [])

    def test_archived_customers_are_not_proposed(self):
        make_customer(last_name="Sarr", is_active=False)
        active = make_customer(last_name="Sarr")
        self.assertEqual([c["id"] for c in self.search("Sarr")], [active.id])

    def test_results_are_limited_and_sorted(self):
        for name in ["Diop C", "Diop A", "Diop B"] + [f"Diop Z{i:02d}" for i in range(CUSTOMER_SEARCH_LIMIT)]:
            make_customer(last_name=name)
        results = self.search("Diop")
        self.assertEqual(len(results), CUSTOMER_SEARCH_LIMIT)
        self.assertEqual([r["name"].split(" ", 1)[1] for r in results[:3]], ["Diop A", "Diop B", "Diop C"])

    def test_no_medical_data_is_returned(self):
        make_customer(last_name="Gueye", medical_conditions="Asthme")
        result = self.search("Gueye")[0]
        self.assertEqual(set(result), {"id", "name", "phone"})

    def test_query_count_is_constant(self):
        def count(n):
            for _ in range(n):
                make_customer(last_name="Kane")
            with CaptureQueriesContext(connection) as captured:
                self.search("Kane")
            return len(captured)
        self.assertEqual(count(2), count(8))

    def test_access_requires_the_till_permission(self):
        url = reverse("search_customer")
        self.client.logout()
        self.assertEqual(self.client.get(url, {"q": "Diop"}).status_code, 302)
        self.client.force_login(make_user())
        self.assertEqual(self.client.get(url, {"q": "Diop"}).status_code, 403)


class TillPageTests(TestCase):
    def setUp(self):
        self.client.force_login(make_user(groups=["Vendeur"]))

    def test_till_no_longer_embeds_every_customer(self):
        for i in range(30):
            make_customer(last_name=f"Embarqué{i}")
        response = self.client.get(reverse("pos"))
        self.assertNotContains(response, "Embarqué")
        self.assertNotIn("customers", response.context)
        self.assertContains(response, 'id="customerSearch"')
        self.assertContains(response, '<input type="hidden" id="customerSelect" value="">', html=False)

    def test_till_query_count_does_not_depend_on_customers(self):
        def count():
            with CaptureQueriesContext(connection) as captured:
                self.client.get(reverse("pos"))
            return len(captured)
        before = count()
        for _ in range(20):
            make_customer()
        self.assertEqual(count(), before)
