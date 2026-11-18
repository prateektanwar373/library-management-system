"""Start-up behaviour that the normal tests bypass (they always inject a SECRET_KEY)."""
import os
import shutil
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import database  # noqa: E402
from app import create_app  # noqa: E402


class TestStartup(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.db_path = os.path.join(self.tmp, "start.db")
        self._saved = {k: os.environ.pop(k, None) for k in
                       ("LMS_SECRET_KEY", "LMS_ADMIN_USER", "LMS_ADMIN_PASSWORD")}

    def tearDown(self):
        for key, value in self._saved.items():
            if value is not None:
                os.environ[key] = value
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_secret_key_is_generated_and_reused_when_not_configured(self):
        database.init_db(self.db_path, "admin", "password123", seed=False)
        app1 = create_app({"DATABASE": self.db_path})
        key_file = os.path.join(self.tmp, "secret_key")
        self.assertTrue(os.path.exists(key_file))
        self.assertGreaterEqual(len(app1.config["SECRET_KEY"]), 32)
        app2 = create_app({"DATABASE": self.db_path})
        self.assertEqual(app1.config["SECRET_KEY"], app2.config["SECRET_KEY"])

    def test_login_page_works_without_any_test_config(self):
        database.init_db(self.db_path, "admin", "password123", seed=False)
        client = create_app({"DATABASE": self.db_path}).test_client()
        self.assertEqual(client.get("/login").status_code, 200)
        self.assertEqual(client.get("/").status_code, 302)

    def test_database_is_created_automatically_with_env_credentials(self):
        os.environ["LMS_ADMIN_PASSWORD"] = "env-password-1"
        app = create_app({"DATABASE": self.db_path})
        self.assertTrue(os.path.exists(self.db_path))
        client = app.test_client()
        page = client.get("/login").data.decode()
        token = page.split('name="csrf_token" value="')[1].split('"')[0]
        resp = client.post("/login", data={"csrf_token": token, "username": "admin",
                                           "password": "env-password-1"}, follow_redirects=True)
        self.assertIn(b"Welcome back", resp.data)


if __name__ == "__main__":
    unittest.main(verbosity=2)
