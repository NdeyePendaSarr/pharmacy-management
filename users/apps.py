from django.apps import AppConfig
from django.db.models.signals import post_migrate


class UsersConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'users'

    def ready(self):
        # Après chaque migrate (déploiement Render, base de test…), les
        # groupes Pharmacien et Vendeur sont recréés si besoin.
        post_migrate.connect(sync_roles_handler, sender=self, dispatch_uid="users.sync_roles")


def sync_roles_handler(sender, apps=None, **kwargs):
    from .roles import sync_roles
    if apps is None:
        sync_roles()
    else:
        sync_roles(apps)
