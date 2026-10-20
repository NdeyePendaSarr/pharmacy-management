"""
Rôles de l'application, définis dans le code.

Les deux groupes sont (re)synchronisés après chaque `migrate` : les
permissions ci-dessous font foi, une modification faite à la main dans
l'admin sur ces deux groupes est écrasée au déploiement suivant.
"""
from django.apps import apps as global_apps
from django.contrib.auth.management import create_permissions

PHARMACIEN = "Pharmacien"
VENDEUR = "Vendeur"

# Le Pharmacien reçoit toutes les permissions de ces applications.
PHARMACIEN_APPS = ("medications", "sales")

# Le Vendeur tient la caisse : il consulte, il vend, il ne modifie ni les
# prix, ni le stock, ni les fiches clients, et ne supprime rien.
VENDEUR_PERMISSIONS = (
    "medications.view_medication",
    "medications.view_category",
    "sales.view_customer",
    "sales.add_sale",
    "sales.view_sale",
)


def sync_roles(apps=global_apps):
    """
    Crée les groupes et leur attribue leurs permissions (idempotent).

    `apps` est le registre fourni par post_migrate (état des migrations) ;
    hors migration, le registre global suffit.
    """
    try:
        Group = apps.get_model("auth", "Group")
        Permission = apps.get_model("auth", "Permission")
        for label in PHARMACIEN_APPS:
            apps.get_app_config(label)
    except LookupError:
        # migrate partiel : les applications concernées ne sont pas encore migrées.
        return

    # Sur une base neuve, les permissions d'une application ne sont créées
    # qu'au post_migrate de cette application : on s'en assure ici.
    for label in PHARMACIEN_APPS:
        create_permissions(global_apps.get_app_config(label), verbosity=0, apps=apps)

    pharmacien, _ = Group.objects.get_or_create(name=PHARMACIEN)
    pharmacien.permissions.set(Permission.objects.filter(content_type__app_label__in=PHARMACIEN_APPS))

    vendeur, _ = Group.objects.get_or_create(name=VENDEUR)
    vendeur_perms = []
    for dotted in VENDEUR_PERMISSIONS:
        app_label, codename = dotted.split(".")
        vendeur_perms.append(
            Permission.objects.get(content_type__app_label=app_label, codename=codename)
        )
    vendeur.permissions.set(vendeur_perms)
