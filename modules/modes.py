"""The three modes a run can be made in, in one place.

A mode decides two things only: which creator prompt is loaded, and whether a judge is
called. The code is shared: there is one generator, one judge, one loop and one syntax
check. Each mode's prompts and its README are in ``modes/<mode id>/``.

- static_creator: the creator gets only the command; there is no judge.
- static_creator_dynamic_judge: the creator gets only the command; the judge sees the
  scene and the physical facts and sends a rejected tree back, up to three times.
- dynamic_creator: the creator gets the command, the scene and the physical facts;
  there is no judge.
"""

from dataclasses import dataclass
from pathlib import Path

import config
from core.pipeline import StageError


@dataclass(frozen=True)
class Mode:
    id: str                    # 'static_creator', …
    title: str                 # 'Static creator', …
    folder: Path               # config.MODES_DIR / id
    creator_prompt: Path       # folder / 'creator_prompt.txt'
    judge_prompt: Path | None  # folder / 'judge_prompt.txt', or None
    creator_sees_scene: bool   # True only for dynamic_creator

    @property
    def uses_judge(self):
        return self.judge_prompt is not None


def _mode(mode_id, title, judge, creator_sees_scene):
    folder = config.MODES_DIR / mode_id
    return Mode(id=mode_id, title=title, folder=folder,
                creator_prompt=folder / 'creator_prompt.txt',
                judge_prompt=folder / 'judge_prompt.txt' if judge else None,
                creator_sees_scene=creator_sees_scene)


MODES = {mode.id: mode for mode in (
    _mode('static_creator', 'Static creator', judge=False, creator_sees_scene=False),
    _mode('static_creator_dynamic_judge', 'Static creator & Dynamic judge', judge=True,
          creator_sees_scene=False),
    _mode('dynamic_creator', 'Dynamic creator', judge=False, creator_sees_scene=True),
)}


def get(mode_id) -> Mode:
    """The mode with this id; a StageError naming the three ids for anything else."""
    try:
        return MODES[mode_id]
    except (KeyError, TypeError):
        raise StageError(f'Unknown mode {mode_id!r}: use one of '
                         f'{", ".join(MODES)}.') from None


def relative(path):
    """A prompt path as it is recorded: relative to the pipeline folder."""
    try:
        return str(Path(path).relative_to(config.PIPELINE_ROOT))
    except ValueError:
        return str(path)
