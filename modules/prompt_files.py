"""Load a prompt that is split over several files.

A prompt file can pull in another file with a line of its own::

    {{include: generation/actions.txt}}

The path is relative to the file that contains the line. The line is replaced by the
included file's text, so the model receives one continuous prompt. The placeholders
(``{scene_objects}``) are filled in afterwards, on the assembled text.
"""

import re

from core.pipeline import StageError

INCLUDE_PATTERN = re.compile(r'^\{\{include:\s*(.+?)\s*\}\}$', re.MULTILINE)
MAX_DEPTH = 5


def load_prompt(path, _depth=0):
    """Return the text of ``path`` with every include line replaced by its file."""
    if not path.exists():
        raise StageError(f'The prompt file is missing: {path}')
    if _depth > MAX_DEPTH:
        raise StageError(f'Prompt includes are nested too deeply at {path}')

    def expand(match):
        return load_prompt(path.parent / match.group(1), _depth + 1).rstrip('\n')

    return INCLUDE_PATTERN.sub(expand, path.read_text(encoding='utf-8'))
