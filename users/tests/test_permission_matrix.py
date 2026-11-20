"""
Matrice d'autorisations : chaque page de l'application, pour chaque profil
(anonyme, compte sans rôle, Vendeur, Pharmacien, superutilisateur).

Le tableau ROUTES est la référence lisible des droits. Un test vérifie que
toute nouvelle route y est ajoutée : une vue ne peut pas être créée sans
que ses droits soient testés.
"""
from decimal import Decimal

from django.test import TestCase
from django.urls import URLPattern, URLResolver, get_resolver, reverse

from medications.models import Category, Medication, StockMovement
from pharmanps_alou.testing import make_category, make_customer, make_medication, make_user
from sales import services
from sales.models import Customer, Sale

# route : (Vendeur autorisé ?, méthode de modification testée en POST ?)
ROUTES = {
    "dashboard": (True, False),
    "medication_list": (True, False),
    "medication_detail": (True, False),
    "medication_create": (False, True),
    "medication_update": (False, True),
    "medication_delete": (False, True),
    "category_list": (True, False),
    "category_create": (False, True),
    "category_update": (False, True),
    "category_delete": (False, True),
    "stock_movement_create": (False, True),
    "pos": (True, False),
    "search_medication": (True, False),
    "search_customer": (True, False),
    "create_sale": (True, True),
    "sale_list": (True, False),
    "sale_detail": (True, False),
    "sale_invoice": (True, False),
    "customer_list": (True, False),
    "customer_detail": (True, False),
    "customer_sales": (True, False),
    "customer_create": (False, True),
    "customer_update": (False, True),
}
# Routes publiques ou spéciales, testées ailleurs (test_access, test_smoke).
PUBLIC_ROUTES = {"login", "logout", "register", "health"}


def route_names(patterns, namespace=None):
    for pattern in patterns:
        if isinstance(pattern, URLResolver):
            if pattern.namespace == "admin":
                continue
            yield from route_names(pattern.url_patterns, pattern.namespace)
        elif isinstance(pattern, URLPattern) and pattern.name:
            yield pattern.name


class PermissionMatrixTests(TestCase):
    def setUp(self):
        self.category = make_category()
        self.medication = make_medication(category=self.category, quantity=50, selling_price=Decimal("1000"))
        self.customer = make_customer()
        self.sale = services.create_sale(None, {
            "items": [{"medication_id": self.medication.id, "quantity": 1}],
            "payment_method": "carte",
            "customer_id": self.customer.id,
        })

    def url(self, name):
        args = {
            "medication_detail": [self.medication.pk], "medication_update": [self.medication.pk],
            "medication_delete": [self.medication.pk], "stock_movement_create": [self.medication.pk],
            "category_update": [self.category.pk], "category_delete": [self.category.pk],
            "sale_detail": [self.sale.pk], "sale_invoice": [self.sale.pk],
            "customer_detail": [self.customer.pk], "customer_sales": [self.customer.pk],
            "customer_update": [self.customer.pk],
        }.get(name, [])
        return reverse(name, args=args)

    def snapshot(self):
        """État des données que les POST refusés ne doivent pas changer."""
        self.medication.refresh_from_db()
        self.customer.refresh_from_db()
        return (
            Medication.objects.count(), Category.objects.count(), StockMovement.objects.count(),
            Sale.objects.count(), Customer.objects.count(),
            self.medication.name, self.medication.quantity, self.customer.last_name,
        )

    def expected_get(self, name, allowed):
        if not allowed:
            return 403
        # L'API de vente n'accepte que POST.
        return 405 if name == "create_sale" else 200

    def test_every_route_is_in_the_matrix(self):
        names = set(route_names(get_resolver().url_patterns))
        self.assertEqual(names - PUBLIC_ROUTES, set(ROUTES))

    def test_anonymous_is_sent_to_login(self):
        for name in ROUTES:
            with self.subTest(route=name):
                response = self.client.get(self.url(name))
                self.assertEqual(response.status_code, 302)
                self.assertTrue(response.url.startswith(reverse("login")))

    def check_profile(self, user, allowed_for):
        self.client.force_login(user)
        for name, (vendeur_allowed, _) in ROUTES.items():
            allowed = allowed_for(name, vendeur_allowed)
            with self.subTest(route=name, method="GET"):
                self.assertEqual(self.client.get(self.url(name)).status_code, self.expected_get(name, allowed))

    def test_user_without_role_is_refused_everywhere(self):
        self.check_profile(make_user(), lambda name, vendeur: False)

    def test_vendeur(self):
        self.check_profile(make_user(groups=["Vendeur"]), lambda name, vendeur: vendeur)

    def test_pharmacien(self):
        self.check_profile(make_user(groups=["Pharmacien"]), lambda name, vendeur: True)

    def test_superuser(self):
        self.check_profile(make_user(superuser=True), lambda name, vendeur: True)

    def test_refused_post_changes_nothing(self):
        # Un Vendeur qui envoie directement un formulaire réservé : 403, rien ne change.
        self.client.force_login(make_user(groups=["Vendeur"]))
        payloads = {
            "medication_create": {"name": "X", "dci": "X", "barcode": "NEW1", "form": "comprimé", "dosage": "1",
                                  "purchase_price": "1", "selling_price": "2", "min_quantity": "1",
                                  "expiry_date": "2030-01-01"},
            "medication_update": {"name": "Renommé"},
            "medication_delete": {},
            "category_create": {"name": "Nouvelle"},
            "category_update": {"name": "Renommée"},
            "category_delete": {},
            "stock_movement_create": {"movement_type": "perte", "quantity": "5"},
            "customer_create": {"first_name": "A", "last_name": "B", "phone": "1", "customer_type": "particulier",
                                "credit_limit": "0"},
            "customer_update": {"first_name": "A", "last_name": "Modifié", "phone": "1",
                                "customer_type": "particulier", "credit_limit": "0"},
        }
        self.assertEqual(
            set(payloads),
            {name for name, (vendeur, post) in ROUTES.items() if post and not vendeur},
        )
        before = self.snapshot()
        for name, data in payloads.items():
            with self.subTest(route=name):
                self.assertEqual(self.client.post(self.url(name), data).status_code, 403)
        self.assertEqual(self.snapshot(), before)
