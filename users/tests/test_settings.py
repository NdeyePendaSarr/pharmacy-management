"""
Point 8 : réglages de production.

Ces tests lancent Django dans un sous-processus avec les variables
d'environnement de production (DEBUG=False), pour vérifier la vraie
configuration et non celle, adaptée, du lanceur de tests.
"""
import os
import subprocess
import sys
from pathlib import Path

from django.conf import settings
from django.test import TestCase
from django.urls import reverse

from pharmanps_alou.testing import make_user

BASE_DIR = Path(settings.BASE_DIR)
PROD_ENV = {
    "DEBUG": "False",
    "SECRET_KEY": "test-only-" + "x9Kp2mQ7vR4tW8yZ3bN6cF1hJ5lD0sG" * 2,
}


def run_django(code, **extra_env):
    env = {key: value for key, value in os.environ.items() if not key.startswith("CLOUDINARY_")}
    env.update(PROD_ENV, **extra_env)
    script = (
        "import django, os; os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'pharmanps_alou.settings'); "
        "django.setup(); " + code
    )
    result = subprocess.run([sys.executable, "-c", script], cwd=BASE_DIR, env=env, capture_output=True, text=True)
    return result


class ProductionSettingsTests(TestCase):
    def test_static_files_use_compressed_manifest_storage(self):
        result = run_django(
            "from django.core.files.storage import storages; print(type(storages['staticfiles']).__name__)"
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.strip(), "CompressedManifestStaticFilesStorage")

    def test_media_use_cloudinary_when_configured(self):
        code = "from django.core.files.storage import storages; print(type(storages['default']).__name__)"
        local = run_django(code)
        self.assertEqual(local.stdout.strip(), "FileSystemStorage", local.stderr)
        cloud = run_django(code, CLOUDINARY_CLOUD_NAME="demo", CLOUDINARY_API_KEY="k", CLOUDINARY_API_SECRET="s")
        self.assertEqual(cloud.stdout.strip(), "MediaCloudinaryStorage", cloud.stderr)

    def test_removed_settings_are_gone(self):
        result = run_django(
            "from django.conf import settings; "
            "print([n for n in ('STATICFILES_STORAGE', 'DEFAULT_FILE_STORAGE', 'SECURE_BROWSER_XSS_FILTER') "
            "if hasattr(settings, n)])"
        )
        self.assertEqual(result.stdout.strip(), "[]", result.stderr)

    def test_check_deploy_is_clean(self):
        result = subprocess.run(
            [sys.executable, "manage.py", "check", "--deploy", "--fail-level", "WARNING"],
            cwd=BASE_DIR, env={**os.environ, **PROD_ENV}, capture_output=True, text=True,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)


class LoginRateLimitTests(TestCase):
    def setUp(self):
        self.user = make_user(username="caissiere", groups=["Vendeur"])

    def login(self, password):
        return self.client.post(reverse("login"), {"username": "caissiere", "password": password})

    def test_account_is_locked_after_repeated_failures(self):
        for _ in range(5):
            self.login("mauvais-mot-de-passe")
        response = self.login("x-Test-Pass-123")  # le bon mot de passe ne suffit plus
        self.assertEqual(response.status_code, 429)
        self.assertContains(response, "Trop de tentatives", status_code=429)
        self.assertNotIn("_auth_user_id", self.client.session)

    def test_successful_login_still_works(self):
        self.login("mauvais-mot-de-passe")
        response = self.login("x-Test-Pass-123")
        self.assertRedirects(response, reverse("dashboard"))
