"""
Outils partagés par les tests des trois applications.

Les fabriques créent des objets valides avec des valeurs par défaut
raisonnables : chaque test ne précise que ce qui compte pour lui.
"""
from datetime import timedelta
from decimal import Decimal
from itertools import count

from django.contrib.auth.models import User
from django.utils import timezone

_seq = count(1)


def make_user(username=None, superuser=False, groups=()):
    username = username or f"user{next(_seq)}"
    if superuser:
        user = User.objects.create_superuser(username=username, password="x-Test-Pass-123")
    else:
        user = User.objects.create_user(username=username, password="x-Test-Pass-123")
    for name in groups:
        from django.contrib.auth.models import Group
        user.groups.add(Group.objects.get(name=name))
    return user


def make_category(name=None):
    from medications.models import Category
    return Category.objects.create(name=name or f"Catégorie {next(_seq)}")


def make_medication(**overrides):
    from medications.models import Medication
    n = next(_seq)
    values = {
        "name": f"Médicament {n}",
        "dci": f"DCI {n}",
        "barcode": f"BAR{n:08d}",
        "category": None,
        "form": "comprimé",
        "dosage": "500mg",
        "purchase_price": Decimal("600.00"),
        "selling_price": Decimal("1000.00"),
        "quantity": 50,
        "min_quantity": 10,
        "expiry_date": timezone.localdate() + timedelta(days=365),
    }
    values.update(overrides)
    return Medication.objects.create(**values)


def make_customer(**overrides):
    from sales.models import Customer
    n = next(_seq)
    values = {
        "first_name": "Awa",
        "last_name": f"Diop {n}",
        "phone": f"77{n:07d}",
        "credit_limit": Decimal("0"),
    }
    values.update(overrides)
    return Customer.objects.create(**values)
