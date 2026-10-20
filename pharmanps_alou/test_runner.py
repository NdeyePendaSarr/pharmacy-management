from django.test.runner import DiscoverRunner
from django.test.utils import override_settings


class TestRunner(DiscoverRunner):
    """
    Lanceur de tests du projet.

    En production, les fichiers statiques utilisent le manifeste de WhiteNoise,
    produit par collectstatic. Les tests n'exécutent pas collectstatic : ils
    utilisent le stockage statique simple, sans rien changer d'autre.
    """

    def setup_test_environment(self, **kwargs):
        super().setup_test_environment(**kwargs)
        from django.conf import settings

        storages = {**settings.STORAGES, "staticfiles": {
            "BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage",
        }}
        self._storage_override = override_settings(STORAGES=storages)
        self._storage_override.enable()

    def teardown_test_environment(self, **kwargs):
        self._storage_override.disable()
        super().teardown_test_environment(**kwargs)
