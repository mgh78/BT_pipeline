"""One run of the pipeline: its id, its mode, its directory and its artifacts.

Every artifact a stage produces - the exact prompt it sent, the raw model reply, the
generated code, the check report, the tree image - is written under
``data/runs/<mode id>/<run id>/`` so that any past run can be reopened and inspected in
full.

Runs made before there were modes sit directly in ``data/runs/<run id>/``. They are
listed and opened as they are, never moved: their mode is read from their
``summary.json`` (see :func:`mode_of_summary`) and shown with "(old run)", because many
of them rewrote the command first (the enrichment stage that no longer exists).
"""

import datetime
import json
import shutil
from dataclasses import dataclass, field
from pathlib import Path

import config
from modules import modes


def new_run_id():
    """Return a run id that sorts chronologically: 2026-10-15_14-22-07_8f3a."""
    stamp = datetime.datetime.now().strftime('%Y-%m-%d_%H-%M-%S')
    suffix = f'{abs(hash(stamp + str(datetime.datetime.now().microsecond))) % 0xffff:04x}'
    return f'{stamp}_{suffix}'


def mode_of_summary(summary):
    """The mode id a stored run was made in, from its ``summary.json``.

    A run made in a mode records it. An old run records only whether the judge was on:
    ``loop.judge_enabled`` false is the Static creator; true, or missing (the runs made
    before there was a baseline), is the Static creator & Dynamic judge.
    """
    loop = summary.get('loop') or {}
    recorded = (loop.get('mode') or {}).get('id') or summary.get('mode')
    if recorded in modes.MODES:
        return recorded
    if loop.get('judge_enabled') is False:
        return 'static_creator'
    return 'static_creator_dynamic_judge'


@dataclass(frozen=True)
class StoredRun:
    """A run on disk, as the run menu lists it."""

    run_id: str
    directory: Path
    mode: str           # a mode id
    old: bool           # True for a run made before there were modes

    @property
    def mode_title(self):
        title = modes.get(self.mode).title
        return f'{title} (old run)' if self.old else title

    @property
    def label(self):
        return f'{self.run_id} · {self.mode_title}'


def _read_summary(directory):
    try:
        return json.loads((directory / 'summary.json').read_text(encoding='utf-8'))
    except (OSError, json.JSONDecodeError):
        return {}


def _stored(directory, old):
    """A run in a mode folder has that folder's mode; an old run, its summary's."""
    mode = (directory.parent.name if not old
            else mode_of_summary(_read_summary(directory)))
    return StoredRun(run_id=directory.name, directory=directory, mode=mode, old=old)


@dataclass
class RunContext:
    """Holds the identity, the mode and the output directory of a single pipeline run."""

    scene: str | None = None
    mode: str = config.DEFAULT_MODE
    run_id: str = field(default_factory=new_run_id)
    created_at: datetime.datetime = field(default_factory=datetime.datetime.now)

    def __post_init__(self):
        mode = modes.get(self.mode)
        while RunContext.find(self.run_id) is not None:   # unique across every mode
            self.run_id = new_run_id()
        self._directory = config.RUNS_DIR / mode.id / self.run_id
        folder = self._directory.parent
        if not folder.exists():
            folder.mkdir(parents=True)
            (folder / 'README.txt').write_text(
                f'The runs of the {mode.title} mode ({mode.id}). The mode is described in '
                f'modes/{mode.id}/README.md.\n', encoding='utf-8')
        self._directory.mkdir(parents=True, exist_ok=True)

    @property
    def directory(self) -> Path:
        return self._directory

    def path(self, name) -> Path:
        """Return the path of an artifact inside this run's directory."""
        path = self.directory / name
        path.parent.mkdir(parents=True, exist_ok=True)
        return path

    # --- Writing artifacts ---------------------------------------------------

    def write_text(self, name, text) -> Path:
        path = self.path(name)
        path.write_text(str(text), encoding='utf-8')
        return path

    def write_json(self, name, payload) -> Path:
        path = self.path(name)
        path.write_text(json.dumps(payload, indent=2, ensure_ascii=False, default=str),
                        encoding='utf-8')
        return path

    def copy_in(self, source, name) -> Path:
        """Copy a file (such as the scene photo) into the run directory."""
        path = self.path(name)
        shutil.copyfile(source, path)
        return path

    # --- Reading past runs ---------------------------------------------------

    @classmethod
    def existing_runs(cls):
        """Every stored run, in the three mode folders and the old flat ones, newest first."""
        root = config.RUNS_DIR
        if not root.exists():
            return []
        runs = []
        for mode_id in modes.MODES:
            folder = root / mode_id
            if folder.is_dir():
                runs += [_stored(path, old=False) for path in folder.iterdir()
                         if path.is_dir()]
        runs += [_stored(path, old=True) for path in root.iterdir()
                 if path.is_dir() and (path / 'summary.json').is_file()]
        return sorted(runs, key=lambda run: run.run_id, reverse=True)

    @staticmethod
    def find(run):
        """The StoredRun for a run id or a run folder, wherever it is; None if there is none.

        ``run`` is an id (``2026-11-05_13-15-22_f873``), or the path of a run folder:
        ``data/runs/<mode id>/<run id>`` or, for an old run, ``data/runs/<run id>``.
        """
        root = config.RUNS_DIR
        path = Path(run)
        if len(path.parts) > 1 or path.is_dir():
            for candidate in (path, config.PIPELINE_ROOT / path):
                if (candidate / 'summary.json').is_file():
                    candidate = candidate.resolve()
                    return _stored(candidate, old=candidate.parent.name not in modes.MODES)
            return None
        for mode_id in modes.MODES:
            if (root / mode_id / run).is_dir():
                return _stored(root / mode_id / run, old=False)
        if (root / run / 'summary.json').is_file():
            return _stored(root / run, old=True)
        return None

    @classmethod
    def load(cls, run):
        """Return a context pointing at an existing run directory (an id or a path)."""
        stored = cls.find(run)
        if stored is None:
            raise FileNotFoundError(f'There is no run {run} in {config.RUNS_DIR}.')
        context = cls.__new__(cls)
        context.run_id = stored.run_id
        context.mode = stored.mode
        context.created_at = datetime.datetime.now()
        context._directory = stored.directory
        context.scene = _read_summary(stored.directory).get('scene')
        return context
