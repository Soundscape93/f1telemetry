"""Drift guards on the Inno Setup script (PRIORITIES C8b).

The installer's firewall rule hard-codes a port and an executable name that are really owned by
Python - ``LiveUDPSource``'s default port and the PyInstaller spec's ``name``. Nothing links them, and
the failure mode when they drift is the worst kind: a rule that opens the wrong port, a recording
that receives nothing, and no error anywhere. Qt-free, like every suite here.
"""
from __future__ import annotations

import inspect
import re
import unittest
from pathlib import Path

from f1telemetry.src.ingest.sources import LiveUDPSource

_REPO_ROOT = Path(__file__).resolve().parent.parent
_ISS = _REPO_ROOT / "packaging" / "installer" / "f1telemetry.iss"
_SPEC = _REPO_ROOT / "packaging" / "f1telemetry.spec"


def _define(text: str, name: str) -> str:
    """The value of an Inno ``#define NAME "value"`` line."""
    match = re.search(rf'^#define\s+{name}\s+"([^"]*)"', text, re.MULTILINE)
    if match is None:
        raise AssertionError(f"no #define {name} in {_ISS.name}")
    return match.group(1)


class InstallerScriptTest(unittest.TestCase):
    def setUp(self):
        self.text = _ISS.read_text(encoding="utf-8")

    def test_the_firewall_rule_opens_the_port_the_recorder_actually_binds(self):
        expected = inspect.signature(LiveUDPSource.__init__).parameters["port"].default
        self.assertEqual(_define(self.text, "TelemetryPort"), str(expected))

    def test_the_rule_is_inbound_udp(self):
        """Outbound or TCP would be a rule that exists, looks right, and does nothing."""
        add = next(l for l in self.text.splitlines() if "firewall add rule" in l)
        self.assertIn("dir=in", add)
        self.assertIn("protocol=UDP", add)
        self.assertIn("action=allow", add)

    def test_the_rule_is_deleted_before_it_is_added(self):
        """Otherwise a reinstall stacks duplicate rules under the same name."""
        self.assertLess(
            self.text.index("firewall delete rule"),
            self.text.index("firewall add rule"),
        )

    def test_the_uninstaller_also_removes_the_rule(self):
        """A rule naming a deleted exe is litter."""
        uninstall = self.text[self.text.index("[UninstallRun]"):]
        self.assertIn("firewall delete rule", uninstall)

    def test_the_installed_exe_name_matches_the_pyinstaller_spec(self):
        exe = _define(self.text, "ExeName")
        self.assertTrue(exe.endswith(".exe"))
        self.assertIn(f'name="{exe.removesuffix(".exe")}"', _SPEC.read_text(encoding="utf-8"))

    def test_it_is_a_per_machine_admin_install_with_no_override(self):
        """The firewall rule needs elevation, and /CURRENTUSER would give a second install shape
        that is never tested. Both lines are load-bearing - see the script header."""
        self.assertIn("PrivilegesRequired=admin", self.text)
        self.assertIn("PrivilegesRequiredOverridesAllowed=\n", self.text)

    def test_nothing_offers_to_launch_the_app_from_the_elevated_installer(self):
        """The invariant C8b must not break: a postinstall launch would run the app as ADMIN and
        create the data root in the wrong user profile."""
        self.assertNotIn("postinstall", self.text)


if __name__ == "__main__":
    unittest.main()
