"""
Crée le compte de démonstration (rôle Vendeur) à partir de variables
d'environnement, uniquement s'il n'existe pas déjà. Sûr à lancer à chaque
déploiement, comme init_admin.

Variables attendues (définies dans Render → Environment) :
  DEMO_USERNAME, DEMO_PASSWORD

Le compte n'a que les droits du groupe Vendeur : caisse, ventes, lecture
des médicaments et des clients. Il ne voit pas les données médicales.
"""
import os
from django.core.management.base import BaseCommand
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group

from users.roles import VENDEUR, sync_roles


class Command(BaseCommand):
    help = "Crée le compte de démonstration Vendeur depuis les variables d'environnement (idempotent)."

    def handle(self, *args, **options):
        User = get_user_model()
        username = os.environ.get("DEMO_USERNAME")
        password = os.environ.get("DEMO_PASSWORD")

        if not username or not password:
            self.stdout.write(self.style.WARNING(
                "DEMO_USERNAME ou DEMO_PASSWORD absent — création du compte de démonstration ignorée."
            ))
            return

        sync_roles()
        vendeur = Group.objects.get(name=VENDEUR)

        user, created = User.objects.get_or_create(username=username)
        if created:
            user.set_password(password)
            user.save()

        if user.is_staff or user.is_superuser:
            self.stdout.write(self.style.ERROR(
                f"'{username}' est un compte administrateur : il ne sera pas utilisé comme compte de démonstration."
            ))
            return

        # Le compte de démo n'a que le rôle Vendeur, même s'il a été modifié entre-temps.
        user.groups.set([vendeur])

        if created:
            self.stdout.write(self.style.SUCCESS(f"Compte de démonstration '{username}' créé (rôle Vendeur)."))
        else:
            self.stdout.write(self.style.SUCCESS(
                f"Le compte de démonstration '{username}' existe déjà — rôle Vendeur vérifié."
            ))
