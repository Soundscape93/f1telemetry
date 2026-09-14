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
* Linux - a systemd-logind inhibitor lock, per *process*: held as long as a child keeps the
  lock's file descriptor open, so thread placement is irrelevant and the lock is released
  automatically if we crash.

A lock screen is not the failure mode on either platform - it doesn't suspend background
processes. Actual suspend-to-RAM is, and it looks identical on both.
"""
from __future__ import annotations

import contextlib
import logging
import subprocess
import sys
from collections.abc import Generator

log = logging.getLogger(__name__)

_ES_CONTINUOUS = 0x80000000          # hold until cleared, rather than a one-shot nudge
_ES_SYSTEM_REQUIRED = 0x00000001     # don't sleep
_ES_DISPLAY_REQUIRED = 0x00000002    # don't blank the display - screen-off can itself trigger standby

# PowerDevil (KDE) copies logind *block* locks into its own inhibitions: "sleep" becomes
# InterruptSession, which is what its idle auto-suspend checks, and "idle" becomes
# ChangeScreenSettings, which only stops dimming and screen-off. So "idle" alone would not keep
# a KDE machine awake - "sleep" is the half that matters. PowerDevil enforces a new lock only
# after a 5 s grace period, so a check made sooner reads as "not honoured".
# "block", not "block-weak": PowerDevil only mirrors "block", and logind lets a user's own
# suspend request override their weak lock - PowerDevil runs as that same user.
_LOGIND_WHAT = "idle:sleep"
_LOGIND_WHO = "f1telemetry"
_LOGIND_WHY = "recording telemetry"

# systemd-inhibit only has to reach the system bus; if it's still alive after this it got the
# lock, and if it exited it was refused.
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
    """Hold a systemd-logind inhibitor lock for the duration of the block.

    Going through the systemd-inhibit binary rather than D-Bus keeps this dependency-free: the
    lock is a file descriptor, and receiving one over D-Bus needs a full client library that
    would then have to be taught to PyInstaller. systemd-inhibit holds that descriptor and runs
    ``cat``, which exits when its stdin closes - so closing the pipe releases the lock with no
    signals and nothing orphaned, and if we die instead the kernel closes the pipe for us.
    """
    try:
        proc = subprocess.Popen(
            ["systemd-inhibit", f"--what={_LOGIND_WHAT}", "--mode=block",
             f"--who={_LOGIND_WHO}", f"--why={_LOGIND_WHY}", "cat"],
            stdin=subprocess.PIPE, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
    except OSError as exc:          # not on PATH (non-systemd box), or not executable
        log.warning("could not request stay-awake: %s - the machine may sleep mid-recording", exc)
        yield
        return

    try:
        proc.wait(timeout=_INHIBIT_CONFIRM_SECONDS)
    except subprocess.TimeoutExpired:
        log.info("stay-awake active for this recording (logind inhibitor: %s)", _LOGIND_WHAT)
    else:                           # exited already, so the lock was refused; stderr says why
        detail = (proc.stderr.read() or b"").decode(errors="replace").strip()
        log.warning("stay-awake request refused (%s) - the system may sleep mid-recording",
                    detail or f"systemd-inhibit exited {proc.returncode}")
        _release(proc)
        yield
        return

    try:
        yield
    finally:
        _release(proc)
        log.info("stay-awake released")


def _release(proc: subprocess.Popen[bytes]) -> None:
    """Drop the lock: EOF on stdin ends ``cat``, which ends systemd-inhibit, which closes the fd."""
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
