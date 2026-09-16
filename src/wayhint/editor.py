"""Open a hint's YAML in the configured editor. The only place that spawns a user process.

``EditorConfig.argv`` does plain placeholder substitution; the result is passed to ``Popen`` as
a list with ``shell=False``. Nothing from YAML/Herdr/Wayfire enters the argv except the sheet's
own path, the line number and the hint id (which validation restricted to ``[A-Za-z0-9._-]``).
"""

from __future__ import annotations

import logging
import shutil
import subprocess
from pathlib import Path

from wayhint.config import EditorConfig

log = logging.getLogger(__name__)


class EditorError(RuntimeError):
    """Safe to display in the overlay."""


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
