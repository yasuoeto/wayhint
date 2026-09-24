"""ProcAdapter against a fake ``/proc`` tree.

The shape of the tree is the whole point of these tests: the adapter is a reader of kernel files,
so the fixture writes the files exactly as ``proc(5)`` describes them (including the parenthesised
``comm`` in ``stat``) and the adapter is pointed at it through ``proc.PROC``.
"""

import logging
import tempfile
import unittest
from pathlib import Path

from wayhint.context import proc as proc_mod
from wayhint.context.proc import ProcAdapter
from wayhint.matcher import strip_pid_suffix

TTY = 34816  # any non-zero tty_nr; the value itself never matters, only that it is not 0
TTY2 = 34817  # a second terminal's tty, so two windows do not share a foreground group


def setUpModule() -> None:
    logging.disable(logging.CRITICAL)  # the adapter logs every declined lookup at DEBUG


def tearDownModule() -> None:
    logging.disable(logging.NOTSET)


class Proc:
    """Builds ``/proc/<pid>/{comm,stat,cmdline,exe,cwd,task/<pid>/children}``."""

    def __init__(self, root: Path, children_file: bool = True) -> None:
        self.root = root
        self.children_file = children_file
        self.kids: dict[int, list[int]] = {}

    def add(
        self,
        pid: int,
        exe: str,
        argv: list[str] | None = None,
        ppid: int = 1,
        pgrp: int | None = None,
        tty: int = 0,
        tpgid: int = -1,
        cwd: str = "/home/u",
        comm: str | None = None,
    ) -> None:
        argv = argv if argv is not None else [exe]
        name = comm if comm is not None else exe.rsplit("/", 1)[-1]
        d = self.root / str(pid)
        (d / "task" / str(pid)).mkdir(parents=True)
        (d / "comm").write_text(name + "\n")
        # pid (comm) state ppid pgrp session tty_nr tpgid ... -- only the first eight are read.
        fields = [pid, f"({name})", "S", ppid, pgrp if pgrp is not None else pid, 1, tty, tpgid]
        (d / "stat").write_text(" ".join(str(f) for f in fields) + " 0 0 0 0\n")
        (d / "cmdline").write_text("\0".join(argv) + "\0")
        (d / "exe").symlink_to(exe)
        (d / "cwd").symlink_to(cwd)
        self.kids.setdefault(ppid, []).append(pid)

    def finish(self) -> None:
        if not self.children_file:
            return  # kernel without CONFIG_PROC_CHILDREN: the adapter falls back to ppid
        for pid in (int(p.name) for p in self.root.iterdir()):
            kids = self.kids.get(pid, [])
            (self.root / str(pid) / "task" / str(pid) / "children").write_text(
                " ".join(str(k) for k in kids)
            )


class PidSuffixTest(unittest.TestCase):
    """The ``<app-id>.p<pid>`` convention a launcher puts on each terminal window (0027)."""

    def test_split(self) -> None:
        cases = {
            "foot": ("foot", None),  # no convention: nothing to strip
            "foot.p12": ("foot", 12),
            "foot.px": ("foot.px", None),  # only digits count
            "com.mitchellh.ghostty.p7": ("com.mitchellh.ghostty", 7),  # reverse-DNS app ids too
            None: (None, None),
        }
        for app_id, expect in cases.items():
            with self.subTest(app_id=app_id):
                self.assertEqual(strip_pid_suffix(app_id), expect)


class ProcAdapterTest(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.addCleanup(self.tmp.cleanup)
        original = proc_mod.PROC
        proc_mod.PROC = self.root
        self.addCleanup(setattr, proc_mod, "PROC", original)

    def build(self, children_file: bool = True) -> Proc:
        return Proc(self.root, children_file=children_file)

    def test_applies_to(self) -> None:
        a = ProcAdapter()
        self.assertTrue(a.applies_to("foot"))
        self.assertTrue(a.applies_to("footclient"))
        self.assertTrue(a.applies_to("foot.p12345"))  # the pid suffix does not change the terminal
        self.assertTrue(a.applies_to("kitty.p12345"))
        self.assertTrue(a.applies_to("alacritty.p12345"))
        self.assertFalse(a.applies_to("Alacritty"))  # the wrapper lower-cases it (TERMINALS.md)
        self.assertFalse(a.applies_to("herdr"))  # Herdr answers for itself
        self.assertFalse(a.applies_to("org.inkscape.Inkscape"))
        self.assertFalse(a.applies_to(None))

    def test_foot_bash_vi_picks_the_deepest_foreground_process(self) -> None:
        p = self.build()
        p.add(100, "/usr/bin/foot", ppid=1)
        p.add(200, "/usr/bin/bash", ppid=100, pgrp=200, tty=TTY, tpgid=300)
        p.add(300, "/usr/bin/vi", argv=["vi", "notes.txt"], ppid=200, pgrp=300, tty=TTY, tpgid=300)
        p.finish()
        info = ProcAdapter().foreground_process("foot")
        self.assertEqual((info.pid, info.name), (300, "vi"))
        self.assertEqual(info.argv, ("vi", "notes.txt"))
        self.assertEqual(info.cwd, "/home/u")

    def test_the_pid_in_the_app_id_picks_one_of_several_windows(self) -> None:
        """The case ``/proc`` alone cannot do: three foots, and the window says which is which."""
        p = self.build()
        for term in (100, 101, 102):
            p.add(term, "/usr/bin/foot", ppid=1)
        p.add(200, "/usr/bin/bash", ppid=101, pgrp=200, tty=TTY, tpgid=300)
        p.add(300, "/usr/bin/vi", argv=["vi", "notes.txt"], ppid=200, pgrp=300, tty=TTY, tpgid=300)
        p.add(400, "/usr/bin/top", ppid=102, pgrp=400, tty=TTY2, tpgid=400)
        p.finish()
        a = ProcAdapter()
        self.assertEqual(a.foreground_process("foot.p101").name, "vi")
        self.assertEqual(a.foreground_process("foot.p102").name, "top")
        self.assertIsNone(a.foreground_process("foot.p100"))  # that window is sitting at no tty

    def test_a_pid_that_is_not_that_terminal_any_more_is_declined(self) -> None:
        """A closed window leaves an app_id nobody owns, and pids get handed out again."""
        p = self.build()
        p.add(100, "/usr/bin/foot", ppid=1)
        p.add(200, "/usr/bin/bash", ppid=100, pgrp=200, tty=TTY, tpgid=300)
        p.add(300, "/usr/bin/vi", ppid=200, pgrp=300, tty=TTY, tpgid=300)
        p.finish()
        a = ProcAdapter()
        self.assertIsNone(a.foreground_process("foot.p999"))  # gone
        self.assertIsNone(a.foreground_process("foot.p300"))  # recycled: pid 300 is vi, not foot

    def test_a_reverse_dns_app_id_matches_the_last_element_of_comm(self) -> None:
        """``comm`` is 15 characters, so ``com.mitchellh.ghostty`` can only ever match ``ghostty``.

        Checked both ways round: with the pid suffix, and as the single-process case that has to
        find the terminal by name alone.
        """
        p = self.build()
        p.add(100, "/usr/bin/ghostty", ppid=1)
        p.add(200, "/usr/bin/bash", ppid=100, pgrp=200, tty=TTY, tpgid=300)
        p.add(300, "/usr/bin/less", ppid=200, pgrp=300, tty=TTY, tpgid=300)
        p.finish()
        a = ProcAdapter()
        self.assertTrue(a.applies_to("com.mitchellh.ghostty"))
        self.assertEqual(a.foreground_process("com.mitchellh.ghostty.p100").name, "less")
        self.assertEqual(a.foreground_process("com.mitchellh.ghostty").name, "less")

    def test_alacritty_found_by_its_lower_case_app_id(self) -> None:
        """The wrapper's ``alacritty.p<pid>`` equals ``comm``; the default ``Alacritty`` doesn't."""
        p = self.build()
        p.add(100, "/usr/bin/alacritty", ppid=1)
        p.add(200, "/usr/bin/bash", ppid=100, pgrp=200, tty=TTY, tpgid=300)
        p.add(300, "/usr/bin/vi", ppid=200, pgrp=300, tty=TTY, tpgid=300)
        p.finish()
        a = ProcAdapter()
        self.assertEqual(a.foreground_process("alacritty.p100").name, "vi")
        self.assertEqual(a.foreground_process("alacritty").name, "vi")

    def test_two_ptys_under_one_terminal_answer_nothing_rather_than_guess(self) -> None:
        """Tabs and splits: one terminal process, one pty each, and /proc cannot say which is on
        screen. Two foreground processes is not a tie to break -- it is an unanswerable question.
        """
        p = self.build()
        p.add(100, "/usr/bin/foot", ppid=1)
        p.add(200, "/usr/bin/bash", ppid=100, pgrp=200, tty=TTY, tpgid=300)
        p.add(300, "/usr/bin/vi", ppid=200, pgrp=300, tty=TTY, tpgid=300)
        p.add(350, "/usr/bin/tmux", ppid=300, pgrp=350)  # opens a pty of its own
        p.add(400, "/usr/bin/top", ppid=350, pgrp=400, tty=TTY2, tpgid=400)
        p.finish()
        self.assertIsNone(ProcAdapter().foreground_process("foot.p100"))

    def test_a_background_job_on_the_same_pty_is_not_the_foreground_process(self) -> None:
        """What ``docs/TERMINALS.md`` relies on: checking the context must not change the answer."""
        p = self.build()
        p.add(100, "/usr/bin/foot", ppid=1)
        p.add(200, "/usr/bin/bash", ppid=100, pgrp=200, tty=TTY, tpgid=300)
        p.add(300, "/usr/bin/vi", ppid=200, pgrp=300, tty=TTY, tpgid=300)
        p.add(400, "/usr/bin/wayhint", ppid=200, pgrp=400, tty=TTY, tpgid=300)  # backgrounded
        p.finish()
        self.assertEqual(ProcAdapter().foreground_process("foot.p100").name, "vi")

    def test_a_terminal_started_from_a_terminal_is_not_its_own_answer(self) -> None:
        """``foot`` run in the foreground of another foot inherits *that* one's tty and group."""
        p = self.build()
        p.add(100, "/usr/bin/foot", ppid=1, pgrp=100, tty=TTY2, tpgid=100)
        p.add(200, "/usr/bin/bash", ppid=100, pgrp=200, tty=TTY, tpgid=300)
        p.add(300, "/usr/bin/vi", ppid=200, pgrp=300, tty=TTY, tpgid=300)
        p.finish()
        self.assertEqual(ProcAdapter().foreground_process("foot.p100").name, "vi")

    def test_a_self_reporting_program_says_its_window_was_opened_wrong(self) -> None:
        """``herdr`` in a window whose app_id does not say ``herdr`` never reaches its own adapter.

        The hints then stop at "a terminal running herdr" instead of describing the focused tab,
        and nothing on screen explains why. One line at ``wayhintd -v`` does (docs/TERMINALS.md).
        """
        p = self.build()
        p.add(100, "/usr/bin/kitty", ppid=1)
        p.add(200, "/usr/bin/bash", ppid=100, pgrp=200, tty=TTY, tpgid=300)
        p.add(
            300, "/home/u/.local/bin/herdr", argv=["herdr"], ppid=200, pgrp=300, tty=TTY, tpgid=300
        )
        p.finish()
        logging.disable(logging.NOTSET)
        self.addCleanup(logging.disable, logging.CRITICAL)
        with self.assertLogs("wayhint.context.proc", level="INFO") as caught:
            info = ProcAdapter().foreground_process("kitty")
        self.assertEqual(info.name, "herdr")  # still answered, just not as well as it could be
        self.assertIn("herdr", caught.output[0])
        self.assertIn("kitty", caught.output[0])

    def test_an_ordinary_program_says_nothing(self) -> None:
        p = self.build()
        p.add(100, "/usr/bin/kitty", ppid=1)
        p.add(200, "/usr/bin/bash", ppid=100, pgrp=200, tty=TTY, tpgid=300)
        p.add(300, "/usr/bin/vi", ppid=200, pgrp=300, tty=TTY, tpgid=300)
        p.finish()
        logging.disable(logging.NOTSET)
        self.addCleanup(logging.disable, logging.CRITICAL)
        with self.assertNoLogs("wayhint.context.proc", level="INFO"):
            self.assertEqual(ProcAdapter().foreground_process("kitty").name, "vi")

    def test_two_terminals_answer_nothing_rather_than_guess(self) -> None:
        p = self.build()
        p.add(100, "/usr/bin/foot", ppid=1)
        p.add(101, "/usr/bin/foot", ppid=1)
        p.add(300, "/usr/bin/vi", ppid=100, pgrp=300, tty=TTY, tpgid=300)
        p.finish()
        self.assertIsNone(ProcAdapter().foreground_process("foot"))

    def test_an_interpreter_is_named_after_the_script_it_runs(self) -> None:
        p = self.build()
        p.add(100, "/usr/bin/foot", ppid=1)
        p.add(200, "/usr/bin/bash", ppid=100, pgrp=200, tty=TTY, tpgid=300)
        p.add(
            300,
            "/usr/bin/python3.13",
            argv=["python3", "/home/u/tools/script.py", "--once"],
            ppid=200,
            pgrp=300,
            tty=TTY,
            tpgid=300,
            comm="python3",
        )
        p.finish()
        self.assertEqual(ProcAdapter().foreground_process("foot").name, "script.py")

    def test_the_name_is_what_was_typed_not_what_it_resolved_to(self) -> None:
        """Debian's alternatives make ``vi`` a symlink to ``vim.gtk3``; sheets say ``vi``."""
        p = self.build()
        p.add(100, "/usr/bin/foot", ppid=1)
        p.add(200, "/usr/bin/bash", ppid=100, pgrp=200, tty=TTY, tpgid=300)
        p.add(
            300,
            "/usr/bin/vim.gtk3",
            argv=["vi", "notes.txt"],
            ppid=200,
            pgrp=300,
            tty=TTY,
            tpgid=300,
            comm="vim.gtk3",
        )
        p.finish()
        info = ProcAdapter().foreground_process("foot")
        self.assertEqual(info.name, "vi")
        self.assertEqual(info.cmdline, "vi notes.txt")  # cmdline_regex can still find the binary

    def test_a_login_shell_loses_its_leading_dash(self) -> None:
        p = self.build()
        p.add(100, "/usr/bin/foot", ppid=1)
        p.add(200, "/usr/bin/bash", argv=["-bash"], ppid=100, pgrp=200, tty=TTY, tpgid=200)
        p.finish()
        self.assertEqual(ProcAdapter().foreground_process("foot").name, "bash")

    def test_an_unreadable_cmdline_falls_back_to_the_binary(self) -> None:
        p = self.build()
        p.add(100, "/usr/bin/foot", ppid=1)
        p.add(200, "/usr/bin/bash", argv=[], ppid=100, pgrp=200, tty=TTY, tpgid=200)
        p.finish()
        self.assertEqual(ProcAdapter().foreground_process("foot").name, "bash")

    def test_without_children_files_the_tree_comes_from_ppid(self) -> None:
        p = self.build(children_file=False)
        p.add(100, "/usr/bin/foot", ppid=1)
        p.add(200, "/usr/bin/bash", ppid=100, pgrp=200, tty=TTY, tpgid=300)
        p.add(300, "/usr/bin/vi", ppid=200, pgrp=300, tty=TTY, tpgid=300)
        p.finish()
        self.assertEqual(ProcAdapter().foreground_process("foot").pid, 300)

    def test_a_shell_alone_in_the_terminal_is_the_foreground_process(self) -> None:
        p = self.build()
        p.add(100, "/usr/bin/foot", ppid=1)
        p.add(200, "/usr/bin/bash", ppid=100, pgrp=200, tty=TTY, tpgid=200)
        p.finish()
        self.assertEqual(ProcAdapter().foreground_process("foot").name, "bash")

    def test_no_foreground_process_and_a_missing_proc_both_answer_none(self) -> None:
        p = self.build()
        p.add(100, "/usr/bin/foot", ppid=1)  # tty_nr 0: nothing is on a terminal
        p.finish()
        self.assertIsNone(ProcAdapter().foreground_process("foot"))
        proc_mod.PROC = self.root / "gone"
        self.assertIsNone(ProcAdapter().foreground_process("foot"))

    def test_a_comm_with_parentheses_does_not_shift_the_stat_fields(self) -> None:
        p = self.build()
        p.add(100, "/usr/bin/foot", ppid=1)
        p.add(200, "/usr/bin/bash", ppid=100, pgrp=200, tty=TTY, tpgid=300)
        p.add(
            300,
            "/usr/bin/odd name",
            ppid=200,
            pgrp=300,
            tty=TTY,
            tpgid=300,
            comm="odd (name) x",
        )
        p.finish()
        self.assertEqual(ProcAdapter().foreground_process("foot").pid, 300)


if __name__ == "__main__":
    unittest.main()
