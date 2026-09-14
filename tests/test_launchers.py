"""The generated launcher entries.

These are synthesised rather than discovered, so the thing worth testing is not
whether they are found -- it is that renaming one renames it, rather than
orphaning the old entry and adding a second beside it.
"""

import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from common.reconcile import MARKER, identity  # noqa: E402
from importers.launchers import NAMES, import_launchers  # noqa: E402


class LauncherEntryTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.home = self.tmp.name
        self.images = os.path.join(self.home, "images")
        os.makedirs(self.images)
        # Posters are only downloaded when absent, so putting them there keeps
        # this test off the network.
        for name in ("Desktop.png", "Steam.png", "Heroic.png", "Reboot.png"):
            with open(os.path.join(self.images, name), "wb") as handle:
                handle.write(b"\x89PNG\r\n\x1a\n")
        # The UI's launcher is detected by being on disk and executable.
        os.makedirs(os.path.join(self.home, ".local", "bin"))
        self.ui = os.path.join(self.home, ".local", "bin", "sunshine-apps-ui")
        with open(self.ui, "w") as handle:
            handle.write("#!/bin/sh\n")
        os.chmod(self.ui, 0o755)

    def _apps(self):
        return import_launchers(self.home, self.home, self.images, {})

    def _apps_ui(self):
        return next((a for a in self._apps()
                     if a.get(MARKER, {}).get("id") == "apps-ui"), None)

    def test_the_manager_gets_an_entry_when_it_is_installed(self):
        self.assertIsNotNone(self._apps_ui())

    def test_it_is_called_what_we_call_it(self):
        self.assertEqual(self._apps_ui()["name"], "Zz App Manager")

    def test_renaming_it_does_not_change_what_it_is(self):
        """The marker, not the name, is what ties this to the entry already in
        apps.json. If the id moved, a rename would orphan the old entry and add
        a second one beside it."""
        self.assertEqual(identity(self._apps_ui()), ("launcher", "apps-ui"))

    def test_it_sorts_to_the_end_of_the_list(self):
        """Moonlight sorts by name, and a tool belongs after the games."""
        self.assertTrue(NAMES["apps-ui"].startswith("Zz"))

    def test_it_runs_the_launcher_that_was_found(self):
        self.assertEqual(self._apps_ui()["cmd"], self.ui)

    def test_no_entry_when_it_is_not_installed(self):
        os.unlink(self.ui)
        self.assertIsNone(self._apps_ui())

    def test_every_generated_entry_is_marked_as_ours(self):
        for app in self._apps():
            self.assertIn(MARKER, app)

    def test_the_marker_ids_are_the_keys_of_the_name_table(self):
        """So a display name can be changed without touching identity."""
        ids = {a[MARKER]["id"] for a in self._apps()}
        self.assertTrue(ids.issubset(set(NAMES)), ids - set(NAMES))


if __name__ == "__main__":
    unittest.main()
