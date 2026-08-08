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
_WORKFLOW = _REPO_ROOT / ".github" / "workflows" / "release.yml"

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


class InstallerWorkflowTest(unittest.TestCase):
    """The .iss and release.yml agree about define names, or the build fails 10 CI-minutes in."""

    def test_every_required_define_is_passed_by_the_workflow(self):
        iss = _ISS.read_text(encoding="utf-8")
        workflow = _WORKFLOW.read_text(encoding="utf-8")

        # A define is *required* when its #ifndef block raises #error rather than defaulting.
        required = {
            name for name, body in re.findall(
                r"^#ifndef\s+(\w+)\s*\n(.*?)^#endif", iss, re.MULTILINE | re.DOTALL)
            if "#error" in body
        }
        self.assertTrue(required, "no required defines found - did the guard block change shape?")

        passed = set(re.findall(r"/D(\w+)=", workflow))
        self.assertEqual(required - passed, set(),
                         f"release.yml never passes: {sorted(required - passed)}")


class InstallerScriptSyntaxTest(unittest.TestCase):
    """A structural lint, because ISCC only exists on Windows and every syntax error otherwise
    costs a full CI round trip. Not a parser - it just catches the class of typo that makes Inno
    read a comment as a section entry (a `:` where a `;` was meant, which reports as the baffling
    `Unrecognized parameter name ""`)."""

    # A section header, a preprocessor directive, a comment, or a `Name: value` / `Key=value`.
    _VALID = re.compile(r"^([A-Za-z_]\w*\s*[:=]|;|#|\[)")

    def test_every_line_is_something_inno_can_parse(self):
        continuation = False
        offenders = []
        for number, raw in enumerate(_ISS.read_text(encoding="utf-8").splitlines(), 1):
            stripped = raw.strip()
            if not stripped:
                continuation = False
                continue
            if not continuation and not self._VALID.match(stripped):
                offenders.append(f"line {number}: {stripped[:60]!r}")
            # Inno continues an entry onto the next line with a trailing backslash; those lines
            # are fragments and are exempt.
            continuation = raw.rstrip().endswith("\\")
        self.assertEqual(offenders, [], "unparseable line(s) in the .iss:\n  " + "\n  ".join(offenders))


if __name__ == "__main__":
    unittest.main()
