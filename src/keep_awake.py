"""Ask Windows to stay awake while a recording is running.

The recorder is oftne the only thing the machine is doing if the game is running on another machine (e.g. console)
and the Laptop just listens. Noting resets the system idle timer and Windows sleeps. A slept machine machine
receives nothing at all: unlike a merely starved process it can't fall back on the kernel's receive
buffer, because the NIC is down too and the datagrams never arrive (see docs/ROADMAP.md "Windows 
recorder stalls" - an 8 MB buffer caugth 0.3 KB across a 22.3 s stall).

No-op off Windows: a Linux lock screen doesn't suspend background processes and a D-Bus inhabitor
is a diffrent mechanism that deserves a different implementation.
"""
from __future__ import annotations

import contextlib
import logging
import sys
from collections.abc import Iterator

log = logging.getLogger(__name__)

_ES_CONTINUOUS = 0x80000000         # hold until cleared, rather than a one-shot nudge
_ES_SYSTEM_REQUIRED = 0x00000001     # don't sleep
_ES_DISPLAY_REQUIRED = 0x00000002    # don't blank the display - screen-off can itself trigger standby

@contextlib.contextmanager
def keep_awake() -> Iterator[None]:
    """Hold off system sleep for the duration of the block.
    
    Must run on the thread that records: SetThreadExecutionState is per-thread and its flags die
    with the thread that set them. Never fatal - a recording that can't get the request is still
    better than no recording, so failures log and continue.
    """
    if sys.platform != "win32":
        yield
        return
    
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
