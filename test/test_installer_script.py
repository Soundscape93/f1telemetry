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

    def test_the_uninstaller_refuses_to_run_while_the_app_is_open(self):
        """Uninstalling with the app open deleted the docs but left the exe and _internal behind -
        a half-removed install. InitializeUninstall aborts BEFORE anything is removed."""
        self.assertIn("[Code]", self.text)
        self.assertIn("function InitializeUninstall(): Boolean;", self.text)

    def test_the_running_app_check_uses_the_exe_name_define(self):
        """Hard-coding the name here would silently stop detecting the app if the exe is renamed -
        the same drift the port and spec guards exist for."""
        code = self.text[self.text.index("[Code]"):]
        self.assertIn("{#ExeName}", code)

    def test_the_rule_name_states_the_port_the_recorder_actually_binds(self):
        """The rule is deliberately NOT port-qualified, so the port survives only in its NAME -
        which is how a human finds it in the Firewall UI. Two halves, and both are needed: the
        define tracks the code, and the rule name is BUILT from the define rather than repeating
        the literal, so the two cannot drift apart. A rule named 20777 on a build that listens
        elsewhere would send the next debugger down a false trail."""
        expected = inspect.signature(LiveUDPSource.__init__).parameters["port"].default
        self.assertEqual(_define(self.text, "TelemetryPort"), str(expected))

        # _define() parses a simple literal and FirewallRule is now a concatenation, so assert on
        # the raw line instead: it must reference the define, and must not repeat the number.
        rule_line = next(l for l in self.text.splitlines()
                         if l.startswith("#define FirewallRule"))
        self.assertIn("TelemetryPort", rule_line)
        self.assertNotIn(str(expected), rule_line)

    def test_the_installer_requests_a_restart(self):
        """The firewall rule is not reliably effective until Windows restarts, and the failure is
        silent - Record looks like it is working and no data arrives. Removing this turns a known
        limitation straight back into a false bug report."""
        self.assertIn("AlwaysRestart=yes", self.text)

    def test_the_restart_page_explains_why(self):
        """Inno's default restart text is generic; an unexplained reboot reads as gratuitous and
        gets declined, which lands the user in exactly the failure it prevents."""
        self.assertIn("FinishedRestartLabel=", self.text)


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
            # [Code] is Pascal, not Inno's key/value grammar - the lint stops there rather than
            # flagging every `begin` and `end;`.
            if stripped.lower().startswith("[code]"):
                break
            if not stripped:
                continuation = False
                continue
            if not continuation and not self._VALID.match(stripped):
                offenders.append(f"line {number}: {stripped[:60]!r}")
            continuation = raw.rstrip().endswith("\\")
        self.assertEqual(offenders, [], "unparseable line(s) in the .iss:\n  " + "\n  ".join(offenders))

    def test_the_code_section_uses_line_comments_only(self):
        """Pascal's { } block comments are a trap in THIS file specifically: it is full of Inno
        constants written {app} / {cmd} / {sys}, and a } inside a brace comment closes it early,
        so the prose after it is parsed as code. Mandate // and the trap cannot be sprung.

        Only the *code* part of each line is examined - a brace inside a // comment or a string
        literal is harmless, and flagging those was this guard's own first bug."""
        text = _ISS.read_text(encoding="utf-8")
        lower = text.lower()
        if "[code]" not in lower:
            self.skipTest("no [Code] section")

        offenders = []
        for number, line in enumerate(text[lower.index("[code]"):].splitlines(), 1):
            # String literals first, so ExpandConstant('{cmd}') is exempt and a // inside a
            # quoted string cannot truncate the line early. Then drop the line comment.
            bare = re.sub(r"'[^']*'", "", line).split("//", 1)[0]
            if re.search(r"\{(?!#)", bare):     # {# is the preprocessor, not a comment
                offenders.append(f"line {number}: {line.strip()[:60]!r}")

        self.assertEqual(offenders, [],
                         "use // comments in [Code], not { }:\n  " + "\n  ".join(offenders))


if __name__ == "__main__":
    unittest.main()
