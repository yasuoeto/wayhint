"""Open a hint's YAML in the configured editor. The only place that spawns a user process.

``EditorConfig.argv`` does plain placeholder substitution; the result is passed to ``Popen`` as
a list with ``shell=False``. Nothing from YAML/Herdr/compositor enters the argv except the sheet's
own path, the line number and the hint id (which validation restricted to ``[A-Za-z0-9._-]``).

:func:`edit_target` decides *where* to land and is pure, so the choice is testable without GTK.
"""

from __future__ import annotations

import logging
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path

from wayhint.config import EditorConfig
from wayhint.models import Hint, HintSheet

log = logging.getLogger(__name__)


class EditorError(RuntimeError):
    """Safe to display in the overlay."""


@dataclass(frozen=True)
class EditTarget:
    file: Path
    line: int
    hint_id: str


def edit_target(sheet: HintSheet | None, hint: Hint | None) -> EditTarget | None:
    """Where the editor should land, or ``None`` when there is nothing to open.

    A hint's own ``location`` wins over the sheet: with ``nested.parent_tags`` the list mixes in
    hints from the parent sheet, so the selected hint often lives in a different file than the
    active sheet. The sheet only decides the file when no hint is selected.
    """
    if hint is not None:
        return EditTarget(hint.location.file, hint.location.line, hint.id)
    if sheet is not None:
        return EditTarget(sheet.path, 1, sheet.id)
    return None


def open_in_editor(editor: EditorConfig, file: Path, line: int, hint_id: str) -> list[str]:
    """Spawn the editor detached. Returns the argv used (for logging/tests)."""
    argv = editor.argv(file, max(1, line), hint_id)
    if shutil.which(argv[0]) is None:
        raise EditorError(f"editor not found: {argv[0]}")
    try:
        subprocess.Popen(  # noqa: S603 - argv list, shell=False, from validated config
            argv, shell=False, start_new_session=True, stdin=subprocess.DEVNULL
        )
    except OSError as e:
        raise EditorError(f"cannot start editor: {e.strerror or e}") from e
    log.info("editor started: %s", argv[0])
    return argv
