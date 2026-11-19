"""
Listes : nombre de requêtes indépendant du volume (pas de requête par
ligne) et pagination qui garde la recherche et les filtres.
"""
from decimal import Decimal

from django.db import connection
from django.test import TestCase
from django.test.utils import CaptureQueriesContext
from django.urls import reverse

from pharmanps_alou.testing import make_category, make_customer, make_medication, make_user
from sales import services
from sales.views import CUSTOMERS_PER_PAGE, SALES_PER_PAGE
from medications.views import MEDICATIONS_PER_PAGE


class ListQueryCountTests(TestCase):
    def setUp(self):
        self.user = make_user(groups=["Pharmacien"])
        self.client.force_login(self.user)
        self.medication = make_medication(quantity=1000, selling_price=Decimal("1000"))

    def add_data(self, count):
        for _ in range(count):
            category = make_category()
            make_medication(category=category)
            customer = make_customer()
            services.create_sale(self.user, {
                "items": [{"medication_id": self.medication.id, "quantity": 1}],
                "payment_method": "carte",
                "customer_id": customer.id,
            })

    def queries(self, url):
        with CaptureQueriesContext(connection) as captured:
            self.assertEqual(self.client.get(url).status_code, 200)
        return len(captured)

    def test_query_count_does_not_depend_on_the_number_of_rows(self):
        urls = [reverse("sale_list"), reverse("customer_list"), reverse("medication_list"), reverse("category_list")]
        self.add_data(2)
        before = {url: self.queries(url) for url in urls}
        self.add_data(8)
        after = {url: self.queries(url) for url in urls}
        self.assertEqual(before, after)

    def test_customer_sales_query_count_is_constant(self):
        customer = make_customer()

        def sell(count):
            for _ in range(count):
                services.create_sale(self.user, {
                    "items": [{"medication_id": self.medication.id, "quantity": 1}],
                    "payment_method": "carte",
                    "customer_id": customer.id,
                })

        url = reverse("customer_sales", args=[customer.pk])
        sell(2)
        before = self.queries(url)
        sell(8)
        self.assertEqual(self.queries(url), before)

    def test_category_counts_are_correct(self):
        category = make_category(name="Antalgiques")
        make_medication(category=category)
        make_medication(category=category)
        response = self.client.get(reverse("category_list"))
        counts = {c.name: c.medication_count for c in response.context["categories"]}
        self.assertEqual(counts["Antalgiques"], 2)


class PaginationTests(TestCase):
    def setUp(self):
        self.user = make_user(groups=["Pharmacien"])
        self.client.force_login(self.user)

    def make_sales(self, count, customer=None):
        medication = make_medication(quantity=1000)
        for _ in range(count):
            services.create_sale(self.user, {
                "items": [{"medication_id": medication.id, "quantity": 1}],
                "payment_method": "carte",
                "customer_id": (customer or make_customer()).id,
            })

    def test_sales_are_split_into_pages(self):
        self.make_sales(SALES_PER_PAGE + 5)
        url = reverse("sale_list")
        first = self.client.get(url)
        self.assertEqual(len(first.context["sales"]), SALES_PER_PAGE)
        self.assertContains(first, 'rel="next"')
        second = self.client.get(url, {"page": 2})
        self.assertEqual(len(second.context["sales"]), 5)
        # Le total affiché porte sur toutes les ventes, pas sur la page.
        self.assertEqual(first.context["total_sales"], second.context["total_sales"])

    def test_invalid_page_numbers_do_not_fail(self):
        self.make_sales(SALES_PER_PAGE + 5)
        url = reverse("sale_list")
        self.assertEqual(self.client.get(url, {"page": "abc"}).context["page_obj"].number, 1)
        self.assertEqual(self.client.get(url, {"page": "999"}).context["page_obj"].number, 2)

    def test_page_links_keep_the_search(self):
        customer = make_customer(last_name="Sarr")
        self.make_sales(SALES_PER_PAGE + 1, customer=customer)
        response = self.client.get(reverse("sale_list"), {"search": "Sarr"})
        self.assertContains(response, "?search=Sarr&amp;page=2")

    def test_customers_and_medications_are_paginated(self):
        for _ in range(CUSTOMERS_PER_PAGE + 1):
            make_customer()
        for _ in range(MEDICATIONS_PER_PAGE + 1):
            make_medication()
        customers = self.client.get(reverse("customer_list"))
        self.assertEqual(len(customers.context["customers"]), CUSTOMERS_PER_PAGE)
        # L'en-tête annonce le nombre total de clients.
        self.assertContains(customers, f"{CUSTOMERS_PER_PAGE + 1} client(s) enregistré(s)")
        medications = self.client.get(reverse("medication_list"))
        self.assertEqual(len(medications.context["medications"]), MEDICATIONS_PER_PAGE)

    def test_single_page_shows_no_pagination(self):
        self.make_sales(3)
        self.assertNotContains(self.client.get(reverse("sale_list")), 'aria-label="Pagination"')
