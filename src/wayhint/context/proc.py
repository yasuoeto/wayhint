"""``/proc`` adapter: a terminal window → the command running in it.

The only module in the package that reads ``/proc``.

Herdr answers "what is in the focused pane" itself; a plain terminal emulator does not, so the
foreground process has to be found the way a shell finds it: the process group that owns the
terminal's tty. Walk the terminal's descendants and keep the deepest one whose process group is
the tty's foreground group (``pgrp == tpgid``).

Which terminal process draws the focused window is the hard half. No Wayland protocol hands a
client the pid behind a toplevel and labwc has no IPC, so with several windows of the same
terminal ``/proc`` alone cannot tell them apart. The window says so itself instead: a launcher
starts it as ``--app-id foot.p$$`` and :func:`~wayhint.matcher.strip_pid_suffix` reads the pid
back out of the app_id the compositor reports (DECISIONS 0027). Without that suffix the adapter
answers only when exactly one process of that terminal is running.

Everything here is read-only file access. No subprocess, no polling: the adapter runs once per
``show`` / ``refresh``, like every other context lookup. Any surprise from ``/proc`` (a process
that exits mid-walk, a kernel without ``task/*/children``, a container that hides other
processes) means "no answer", never a wrong answer -- a wrong sheet is worse than no sheet.
"""

from __future__ import annotations

import logging
from collections.abc import Callable, Iterable
from pathlib import Path

from wayhint.context.process import process_info_from_mapping
from wayhint.matcher import GENERIC_PROCESS_NAMES, strip_pid_suffix
from wayhint.models import ProcessInfo

log = logging.getLogger(__name__)

PROC = Path("/proc")
"""Root of the procfs. A module variable so tests can point it at a fake tree."""

TERMINAL_APP_IDS = frozenset({"foot", "footclient", "kitty", "com.mitchellh.ghostty"})
"""Terminals whose foreground process is found through ``/proc``, by app_id (pid suffix removed).

Deliberately a constant and not configuration: every entry has to be a terminal emulator that
runs its command as a descendant, which is a property of the program, not a preference. ``herdr``
is not here -- it answers for itself through :mod:`wayhint.context.herdr`. WezTerm is not here
either: it cannot give each window its own app_id, so the pid suffix has nowhere to live
(DECISIONS 0027).
"""

SELF_REPORTING = frozenset({"herdr"})
"""Programs that have an adapter of their own, chosen by app_id rather than by process name.

Finding one of these as *the* foreground process means its window was opened in a way that hides
it from that adapter: the app_id does not match, so the adapter was never asked and the answer
stops at "a terminal running herdr" instead of the tab the user is looking at. Nothing on screen
explains that, so the adapter says so in the log (``docs/TERMINALS.md``).
"""

_PROC_ERRORS = (OSError, ValueError)
"""``/proc`` races with the processes it describes; all of it is expected, none of it is fatal.

``OSError`` covers the interesting cases -- ``FileNotFoundError`` and ``ProcessLookupError`` for a
process that exited between two reads, ``PermissionError`` for one owned by somebody else --
and ``ValueError`` covers a field that is not the number it should be.
"""


class ProcAdapter:
    """Terminal introspection: the app_id says which window, ``/proc`` says what runs in it."""

    def applies_to(self, app_id: str | None) -> bool:
        base, _pid = strip_pid_suffix(app_id)
        return bool(base) and base in TERMINAL_APP_IDS

    def foreground_process(self, app_id: str | None = None) -> ProcessInfo | None:
        try:
            root = self._terminal_pid(app_id)
            if root is None:
                return None
            pid = self._foreground_pid(root)
            if pid is None:
                return None
            info = self._describe(pid)
            if info is not None and info.name in SELF_REPORTING:
                log.info(
                    "%s is running in a window whose app_id is %r; open it with %r in the app_id "
                    "to get hints for what is inside it (docs/TERMINALS.md)",
                    info.name,
                    app_id,
                    info.name,
                )
            return info
        except _PROC_ERRORS as e:
            log.debug("/proc lookup failed: %s", e.__class__.__name__)
            return None

    def _terminal_pid(self, app_id: str | None) -> int | None:
        """The process that draws the focused window, or ``None`` when it would be a guess.

        With the ``.p<pid>`` suffix the window names its own process; the pid is still checked
        against ``/proc``, because a window that closed leaves an app_id nobody owns any more and
        the number may since have been handed to something else entirely.

        Without the suffix the only honest answer is the single-window case: a terminal with two
        windows, or foot's server mode where one process owns every window, is indistinguishable
        in ``/proc``, so the adapter declines rather than pick one.
        """
        base, pid = strip_pid_suffix(app_id)
        if base is None:
            return None
        if pid is not None:
            if not _is_process_of(pid, base):
                log.debug("pid %d from app_id %r is not %s any more", pid, app_id, base)
                return None
            return pid
        found = [p for p in _pids() if _is_process_of(p, base)]
        if len(found) != 1:
            log.debug("%d %s processes in /proc and no pid in the app_id", len(found), base)
            return None
        return found[0]

    def _foreground_pid(self, root: int) -> int | None:
        """Deepest descendant of ``root`` that owns the tty's foreground process group.

        There is one such process *per pty*, and a terminal with tabs or splits owns several.
        ``/proc`` does not say which tab is on screen, so finding more than one tty is not a tie
        to break but a question that cannot be answered: the adapter declines (DECISIONS 0027).
        Within one pty the whole foreground process group can match -- a pipeline, or a shell
        watching its child -- and there the deepest is the one actually in front.

        ``root`` itself never counts. A terminal started from another terminal sits in *that*
        one's foreground group, which says nothing about what it is running.
        """
        children = _child_lookup(root)
        found: list[tuple[int, int, int]] = []  # (tty, depth, pid)
        seen = {root}
        stack = [(root, 0)]
        while stack:
            pid, depth = stack.pop()
            tty = _foreground_tty(pid) if pid != root else None
            if tty is not None:
                found.append((tty, depth, pid))
            for child in children(pid):
                if child not in seen:
                    seen.add(child)
                    stack.append((child, depth + 1))
        ttys = {tty for tty, _depth, _pid in found}
        if len(ttys) != 1:
            log.debug("%d ttys in the foreground below pid %d; not guessing", len(ttys), root)
            return None
        return max(found)[2]

    def _describe(self, pid: int) -> ProcessInfo | None:
        argv = _cmdline(pid)
        return process_info_from_mapping(
            {
                "pid": pid,
                "name": _name(pid, argv),
                "argv": list(argv),
                "cmdline": " ".join(argv),
                "cwd": _link(pid, "cwd"),
            }
        )


def _pids() -> Iterable[int]:
    return sorted(int(p.name) for p in PROC.iterdir() if p.name.isdigit())


def _is_process_of(pid: int, base: str) -> bool:
    """Is ``pid`` a process of the terminal whose app_id base is ``base``?

    An app_id is not a program name: foot's is ``foot`` and equals ``comm`` outright, while a GTK
    terminal's is reverse-DNS (``com.mitchellh.ghostty``) and only its last element does. Both
    forms are accepted and nothing else, which is also what keeps a recycled pid from passing for
    the window that named it. ``comm`` is truncated to 15 characters, so the reverse-DNS form
    could never have matched whole anyway.
    """
    comm = _comm(pid)
    return comm is not None and comm in (base, base.rsplit(".", 1)[-1])


def _comm(pid: int) -> str | None:
    try:
        return (PROC / str(pid) / "comm").read_text().strip()
    except _PROC_ERRORS:
        return None


def _stat_fields(pid: int) -> list[str] | None:
    """Fields of ``/proc/<pid>/stat`` from ``state`` on, i.e. field 3 of ``proc(5)`` at index 0.

    The comm field is in parentheses and may itself contain them (``(a) b``), so the split starts
    after the *last* ``)``.
    """
    try:
        text = (PROC / str(pid) / "stat").read_text()
    except _PROC_ERRORS:
        return None
    rest = text.rpartition(")")[2]
    return rest.split() if rest else None


def _foreground_tty(pid: int) -> int | None:
    """The tty this process is in front of (``pgrp == tpgid``), or ``None`` if it is in front of
    none. The identity of the tty matters, not just that there is one: two of them below the same
    terminal mean two tabs, and no way to tell which one the user is looking at.
    """
    fields = _stat_fields(pid)
    if fields is None or len(fields) < 6:
        return None
    try:
        pgrp, tty_nr, tpgid = int(fields[2]), int(fields[4]), int(fields[5])
    except ValueError:
        return None
    return tty_nr if tty_nr != 0 and pgrp == tpgid else None


def _child_lookup(root: int) -> Callable[[int], list[int]]:
    """``pid -> children``. Uses ``task/*/children`` where the kernel has it, ppid otherwise."""
    if (PROC / str(root) / "task" / str(root) / "children").exists():
        return _children_from_task
    parents: dict[int, list[int]] = {}
    for pid in _pids():
        fields = _stat_fields(pid)
        if fields is None or len(fields) < 2:
            continue
        try:
            ppid = int(fields[1])
        except ValueError:
            continue
        parents.setdefault(ppid, []).append(pid)
    return lambda pid: parents.get(pid, [])


def _children_from_task(pid: int) -> list[int]:
    out: list[int] = []
    try:
        tasks = sorted((PROC / str(pid) / "task").iterdir())
    except _PROC_ERRORS:
        return out
    for task in tasks:
        try:
            text = (task / "children").read_text()
        except _PROC_ERRORS:
            continue
        out.extend(int(token) for token in text.split() if token.isdigit())
    return out


def _cmdline(pid: int) -> tuple[str, ...]:
    try:
        raw = (PROC / str(pid) / "cmdline").read_text()
    except _PROC_ERRORS:
        return ()
    return tuple(part for part in raw.split("\0") if part)


def _name(pid: int, argv: tuple[str, ...]) -> str:
    """What the user typed, not what it resolved to.

    ``argv[0]`` beats ``exe`` because Debian's alternatives turn ``vi`` into ``/usr/bin/vim.gtk3``,
    and a sheet written for ``vim.gtk3`` is not the one anybody would think to write. Somebody who
    does want the real binary has ``cmdline_regex`` (DECISIONS 0027). A login shell arrives as
    ``-bash``: the dash is the shell's own marker, not part of the name.

    Matching is done on the same names the Herdr path produces, so ``python3 review.py`` has to
    arrive as ``review.py`` here too (DECISIONS 0014 D6).
    """
    name = argv[0].rsplit("/", 1)[-1].lstrip("-") if argv else ""
    if not name:  # kernel threads, and anything whose cmdline cannot be read
        exe = _link(pid, "exe")
        name = exe.rsplit("/", 1)[-1] if exe else (_comm(pid) or "")
    if _is_interpreter(name) and len(argv) > 1:
        script = argv[1].rsplit("/", 1)[-1]
        if script and not script.startswith("-"):
            return script
    return name


def _is_interpreter(name: str) -> bool:
    return name in GENERIC_PROCESS_NAMES or name.startswith("python")


def _link(pid: int, name: str) -> str | None:
    try:
        return str((PROC / str(pid) / name).readlink())
    except _PROC_ERRORS:
        return None
