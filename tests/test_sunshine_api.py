"""Tests for the hot-reload path. No network: the HTTP layer is stubbed."""
import json
import os
import stat
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from common import sunshine_api  # noqa: E402
from common.sunshine_api import SunshineAPIError, SunshineClient, load_credentials  # noqa: E402


def conf_dir_with(creds=None, mode=0o600, cacert=True):
    d = tempfile.mkdtemp()
    if cacert:
        os.makedirs(os.path.join(d, "credentials"), exist_ok=True)
        with open(os.path.join(d, "credentials", "cacert.pem"), "w") as f:
            f.write("-----BEGIN CERTIFICATE-----\nnot a real one\n-----END CERTIFICATE-----\n")
    if creds is not None:
        path = os.path.join(d, sunshine_api.CREDENTIALS_FILE)
        with open(path, "w") as f:
            f.write(creds)
        os.chmod(path, mode)
    return d


class TestCredentials(unittest.TestCase):
    def setUp(self):
        for key in ("SUNSHINE_USERNAME", "SUNSHINE_PASSWORD"):
            os.environ.pop(key, None)

    def test_environment_wins(self):
        os.environ["SUNSHINE_USERNAME"] = "u"
        os.environ["SUNSHINE_PASSWORD"] = "p"
        try:
            self.assertEqual(load_credentials("/nonexistent"), ("u", "p"))
        finally:
            del os.environ["SUNSHINE_USERNAME"], os.environ["SUNSHINE_PASSWORD"]

    def test_file_is_read(self):
        d = conf_dir_with("username = admin\npassword = hunter2\n")
        self.assertEqual(load_credentials(d), ("admin", "hunter2"))

    def test_comments_and_blank_lines_are_ignored(self):
        d = conf_dir_with("# mine\n\nusername=admin\npassword=hunter2\n")
        self.assertEqual(load_credentials(d), ("admin", "hunter2"))

    def test_a_world_readable_file_is_refused(self):
        """A password file others can read is not one we should quietly use."""
        d = conf_dir_with("username=a\npassword=b\n", mode=0o644)
        with self.assertRaises(SunshineAPIError) as cm:
            load_credentials(d)
        self.assertIn("readable by others", str(cm.exception))

    def test_missing_file_explains_both_options(self):
        d = conf_dir_with(None)
        with self.assertRaises(SunshineAPIError) as cm:
            load_credentials(d)
        self.assertIn("SUNSHINE_USERNAME", str(cm.exception))
        self.assertIn(sunshine_api.CREDENTIALS_FILE, str(cm.exception))

    def test_half_a_file_is_refused(self):
        d = conf_dir_with("username=admin\n")
        with self.assertRaises(SunshineAPIError):
            load_credentials(d)


class TestTls(unittest.TestCase):
    def test_a_missing_cacert_refuses_rather_than_skipping_verification(self):
        d = conf_dir_with("username=a\npassword=b\n", cacert=False)
        with self.assertRaises(SunshineAPIError) as cm:
            SunshineClient(d)
        self.assertIn("Refusing to send credentials", str(cm.exception))


class TestReload(unittest.TestCase):
    def setUp(self):
        self.d = conf_dir_with("username=admin\npassword=hunter2\n")
        patcher = mock.patch.object(sunshine_api, "_tls_context", return_value=None)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.client = SunshineClient(self.d)
        self.calls = []

    def _stub(self, apps):
        def fake(method, path, body=None):
            self.calls.append((method, path, body))
            if method == "GET":
                return {"apps": apps, "env": {}}
            return {"status": True}
        self.client._request = fake

    def test_reload_reads_then_posts_one_app_back_unchanged(self):
        apps = [{"name": "Desktop", "image-path": "d.png"}, {"name": "Other"}]
        self._stub(apps)
        used = self.client.reload()
        self.assertEqual(used, "Desktop")
        methods = [c[0] for c in self.calls]
        self.assertEqual(methods, ["GET", "POST"])

    def test_the_get_comes_first_because_indices_are_positional(self):
        """Reusing a stale index would overwrite whichever app moved into it."""
        self._stub([{"name": "Desktop"}])
        self.client.reload()
        self.assertEqual(self.calls[0][0], "GET")
        self.assertLess([c[0] for c in self.calls].index("GET"),
                        [c[0] for c in self.calls].index("POST"))

    def test_the_posted_body_is_the_app_plus_its_index(self):
        apps = [{"name": "Desktop", "image-path": "d.png", "exit-on-close": True}]
        self._stub(apps)
        self.client.reload()
        _, _, body = self.calls[1]
        self.assertEqual(body["index"], 0)
        for key, value in apps[0].items():
            self.assertEqual(body[key], value, key)

    def test_posting_does_not_mutate_the_app_we_were_given(self):
        apps = [{"name": "Desktop"}]
        self._stub(apps)
        self.client.reload()
        self.assertNotIn("index", apps[0])

    def test_no_apps_is_an_explicit_error_not_a_silent_success(self):
        self._stub([])
        with self.assertRaises(SunshineAPIError) as cm:
            self.client.reload()
        self.assertIn("nothing to re-save", str(cm.exception))

    def test_reload_sunshine_reports_failure_rather_than_raising(self):
        with mock.patch.object(sunshine_api, "SunshineClient",
                               side_effect=SunshineAPIError("nope")):
            self.assertFalse(sunshine_api.reload_sunshine(self.d))


if __name__ == "__main__":
    unittest.main()
