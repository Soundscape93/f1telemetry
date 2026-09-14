"""Ask the OS to stay awake while a recording is running.

The recorder is often the only thing the machine is doing if the game is running on another
machine (e.g. a console) and the laptop just listens. Nothing resets the system idle timer and
the machine sleeps. A slept machine receives nothing at all: unlike a merely starved process it
can't fall back on the kernel's receive buffer, because the NIC is down too and the datagrams
never arrive (see docs/ROADMAP.md "Windows recorder stalls" - an 8 MB buffer caught 0.3 KB
across a 22.3 s stall).

Two mechanisms, with different scopes:

* Windows - ``SetThreadExecutionState``, per *thread*: the flags die with the thread that set
  them, so this must be entered on the thread that blocks in ``recvfrom``.
* Linux - a systemd-logind inhibitor lock, plus a GNOME session inhibitor under GNOME, per
  *process*: held as long as child processes keep them, so thread placement is irrelevant and
  they are released automatically if we crash.

A lock screen is not the failure mode on either platform - it doesn't suspend background
processes. Actual suspend-to-RAM is, and it looks identical on both.
"""
from __future__ import annotations

import contextlib
import logging
import os
import shutil
import subprocess
import sys
from collections.abc import Generator

log = logging.getLogger(__name__)

_ES_CONTINUOUS = 0x80000000          # hold until cleared, rather than a one-shot nudge
_ES_SYSTEM_REQUIRED = 0x00000001     # don't sleep
_ES_DISPLAY_REQUIRED = 0x00000002    # don't blank the display - screen-off can itself trigger standby

# Only suspend is inhibited, never idle. PowerDevil (KDE) copies logind *block* locks into its own
# inhibitions: "sleep" becomes InterruptSession, which is what its idle auto-suspend checks, while
# "idle" would become ChangeScreenSettings, which only keeps the screen from dimming and turning
# off. Linux doesn't need that - a dark screen doesn't stop a recording - so it would only cost
# battery. (Windows keeps ES_DISPLAY_REQUIRED because screen-off can itself trigger standby there.)
# PowerDevil enforces a new lock only after a 5 s grace period, so a check made sooner reads as
# "not honoured". "block", not "block-weak": PowerDevil only mirrors "block", and logind lets a
# user's own suspend request override their weak lock - PowerDevil runs as that same user. 
_LOGIND_WHAT = "sleep"
_LOGIND_WHO = "f1telemetry"
_LOGIND_WHY = "recording telemetry"

# GNOME's power daemon never looks at logind locks: before an idle suspend it checks only
# gnome-session's own inhibitors, then asks logind to suspend. systemd 257+ refuses that request
# while a "block" lock is held, but older logind ignored locks taken by the user asking - and GNOME
# asks as that user - so on systemd < 257 (Ubuntu 24.04, Debian 12) only a session inhibitor stops
# it. gnome-session-inhibit holds one for as long as its child runs; "suspend" alone, for the same
# reason as above.
_GNOME_INHIBIT = "suspend"

# Each request only has to reach its bus: if the command is still alive after this, every lock in
# it was granted, and if it exited, one was refused.
_INHIBIT_CONFIRM_SECONDS = 0.5


@contextlib.contextmanager
def keep_awake() -> Generator[None]:
    """Hold off system sleep for the duration of the block.

    Never fatal - a recording that can't get the request is still better than no recording, so
    failures log and continue.
    """
    if sys.platform == "win32":
        with _keep_awake_windows():
            yield
    elif sys.platform.startswith("linux"):
        with _keep_awake_linux():
            yield
    else:
        log.info("no stay-awake mechanism for %s - the machine may sleep mid-recording",
                 sys.platform)
        yield


@contextlib.contextmanager
def _keep_awake_windows() -> Generator[None]:
    """SetThreadExecutionState, asserted on the calling thread."""
    import ctypes
    try:
        previous = ctypes.windll.kernel32.SetThreadExecutionState(
            _ES_CONTINUOUS | _ES_SYSTEM_REQUIRED | _ES_DISPLAY_REQUIRED)
    except Exception as exc:
        log.warning("could not request stay-awake: %s", exc)
        yield
        return
    if previous == 0:
        log.warning("stay-awake request refused - the system may sleep mid-recording")
    else:
        log.info("stay-awake active for this recording")
    try:
        yield
    finally:
        ctypes.windll.kernel32.SetThreadExecutionState(_ES_CONTINUOUS)  # clears the flags
        log.info("stay-awake released")


@contextlib.contextmanager
def _keep_awake_linux() -> Generator[None]:
    """Hold a systemd-logind inhibitor lock, and under GNOME a session inhibitor, for the block.

    Going through command-line tools rather than D-Bus keeps this dependency-free: the logind lock
    is a file descriptor and the GNOME inhibitor lives as long as the D-Bus connection that took
    it, and either would need a client library for PyInstaller to bundle. The tools chain into
    ``cat``, which exits when its stdin closes - each tool runs the next and exits when it does -
    so closing the pipe releases everything with no signals and nothing orphaned, and if we die
    instead the kernel closes the pipe for us.
    """
    request = _request_inhibitors()
    if request is None:
        yield
        return
    proc, argv = request
    held = f"logind inhibitor: {_LOGIND_WHAT}"
    if "gnome-session-inhibit" in argv:
        held += f", GNOME session inhibitor: {_GNOME_INHIBIT}"
    log.info("stay-awake active for this recording (%s)", held)
    try:
        yield
    finally:
        _release(proc)
        log.info("stay-awake released")


def _inhibit_commands() -> list[list[str]]:
    """The requests to try, strongest first; each ends in ``cat`` so stdin EOF unwinds it."""
    logind = ["systemd-inhibit", f"--what={_LOGIND_WHAT}", "--mode=block",
              f"--who={_LOGIND_WHO}", f"--why={_LOGIND_WHY}"]
    commands = [logind + ["cat"]]
    desktops = os.environ.get("XDG_CURRENT_DESKTOP", "").split(":")
    if "GNOME" in desktops and shutil.which("gnome-session-inhibit"):
        gnome = ["gnome-session-inhibit", "--inhibit", _GNOME_INHIBIT,
                 "--app-id", _LOGIND_WHO, "--reason", _LOGIND_WHY]
        commands.insert(0, logind + gnome + ["cat"])
    return commands


def _request_inhibitors() -> tuple[subprocess.Popen[bytes], list[str]] | None:
    """Start the strongest request that is granted, or None if none is (and log why)."""
    commands = _inhibit_commands()
    for attempt, argv in enumerate(commands, start=1):
        try:
            proc = subprocess.Popen(argv, stdin=subprocess.PIPE, stdout=subprocess.DEVNULL,
                                    stderr=subprocess.PIPE)
        except OSError as exc:      # not on PATH (non-systemd box), or not executable
            log.warning("could not request stay-awake: %s - the machine may sleep mid-recording", exc)
            return None
        try:
            proc.wait(timeout=_INHIBIT_CONFIRM_SECONDS)
        except subprocess.TimeoutExpired:
            return proc, argv       # still running, so every lock in this request is held
        detail = (proc.stderr.read() or b"").decode(errors="replace").strip()
        detail = detail or f"{argv[0]} exited {proc.returncode}"
        _release(proc)
        if attempt < len(commands):
            log.info("stay-awake with the GNOME session inhibitor refused (%s) - "
                     "retrying with the logind lock alone", detail)
        else:
            log.warning("stay-awake request refused (%s) - the system may sleep mid-recording",
                        detail)
    return None


def _release(proc: subprocess.Popen[bytes]) -> None:
    """Drop the locks: EOF on stdin ends ``cat``, and each tool in the chain exits after it."""
    try:
        if proc.stdin is not None:
            proc.stdin.close()
        if proc.stderr is not None:
            proc.stderr.close()
        proc.wait(timeout=_INHIBIT_CONFIRM_SECONDS)
    except (subprocess.TimeoutExpired, OSError):
        proc.kill()                 # the descriptor dies with the process either way
        with contextlib.suppress(Exception):
            proc.wait(timeout=_INHIBIT_CONFIRM_SECONDS)
