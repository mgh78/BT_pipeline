"""One run of the pipeline: its id, its directory and its artifacts.

Every artifact a stage produces - the exact prompt it sent, the raw model reply, the
generated code, the check report, the tree image - is written under
``data/runs/<run_id>/`` so that any past run can be reopened and inspected in full.
"""

import datetime
import json
import shutil
from dataclasses import dataclass, field
from pathlib import Path

import config


def new_run_id():
    """Return a run id that sorts chronologically: 2026-10-15_14-22-07_8f3a."""
    stamp = datetime.datetime.now().strftime('%Y-%m-%d_%H-%M-%S')
    suffix = f'{abs(hash(stamp + str(datetime.datetime.now().microsecond))) % 0xffff:04x}'
    return f'{stamp}_{suffix}'


@dataclass
class RunContext:
    """Holds the identity and the output directory of a single pipeline run."""

    run_id: str = field(default_factory=new_run_id)
    scene: str | None = None
    created_at: datetime.datetime = field(default_factory=datetime.datetime.now)

    def __post_init__(self):
        self.directory.mkdir(parents=True, exist_ok=True)

    @property
    def directory(self) -> Path:
        return config.RUNS_DIR / self.run_id

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

    # --- Reading a past run --------------------------------------------------

    @classmethod
    def existing_runs(cls):
        """Return the ids of all stored runs, most recent first."""
        if not config.RUNS_DIR.exists():
            return []
        return sorted((p.name for p in config.RUNS_DIR.iterdir() if p.is_dir()), reverse=True)

    @classmethod
    def load(cls, run_id):
        """Return a context pointing at an existing run directory."""
        context = cls.__new__(cls)
        context.run_id = run_id
        context.created_at = datetime.datetime.now()
        summary = config.RUNS_DIR / run_id / 'summary.json'
        context.scene = None
        if summary.exists():
            try:
                context.scene = json.loads(summary.read_text(encoding='utf-8')).get('scene')
            except json.JSONDecodeError:
                pass
        return context
