"""The stage machinery: what a pipeline module is, and how a run moves through them.

Each module is a :class:`Stage`. A stage reads what earlier stages put in the shared
``payload`` and returns a :class:`StageResult` describing what it did. The
:class:`Pipeline` runs them in order, times each one, logs its start and end, writes a
``summary.json`` for the run, and reports every change to an observer so the interface
can follow along while the run is still going.
"""

import datetime
import time
import traceback
from dataclasses import asdict, dataclass, field
from enum import Enum

from core import logging_setup

log = logging_setup.get_logger('pipeline')


class StageStatus(str, Enum):
    IDLE = 'idle'
    RUNNING = 'running'
    PASSED = 'passed'
    FAILED = 'failed'        # the stage itself broke, or a check did not hold
    REJECTED = 'rejected'    # the model declined the command on purpose
    SKIPPED = 'skipped'


# Statuses that stop the run.
TERMINAL = {StageStatus.FAILED, StageStatus.REJECTED}


@dataclass
class Check:
    """One assertion made by the syntax tester.

    A failed check whose ``severity`` is ``'warning'`` is reported but does not fail
    the stage: it marks something the prompt discourages that is still harmless, such
    as a stray import. Only a failed ``'error'`` check stops the run.
    """

    id: str
    title: str
    passed: bool
    message: str = ''
    line: int | None = None
    severity: str = 'error'
    group: str = ''

    @property
    def blocking(self):
        return not self.passed and self.severity == 'error'

    def as_dict(self):
        return asdict(self)


@dataclass
class StageResult:
    """What a stage produced, and everything the interface shows about it."""

    stage: str
    status: StageStatus = StageStatus.IDLE
    summary: str = ''
    detail: dict = field(default_factory=dict)       # free-form, rendered in the GUI
    artifacts: dict = field(default_factory=dict)    # label -> path on disk
    checks: list = field(default_factory=list)       # Check objects, tester only
    error: str | None = None
    duration_s: float = 0.0
    started_at: str = ''

    @property
    def ok(self):
        return self.status in (StageStatus.PASSED, StageStatus.SKIPPED)

    @classmethod
    def from_dict(cls, payload):
        """Rebuild a result from ``summary.json``, so a past run can be reopened."""
        from pathlib import Path

        return cls(
            stage=payload.get('stage', ''),
            status=StageStatus(payload.get('status', 'idle')),
            summary=payload.get('summary', ''),
            detail=payload.get('detail', {}),
            artifacts={k: Path(v) for k, v in (payload.get('artifacts') or {}).items()},
            checks=[Check(**c) for c in payload.get('checks', [])],
            error=payload.get('error'),
            duration_s=payload.get('duration_s', 0.0),
            started_at=payload.get('started_at', ''))

    def as_dict(self):
        payload = asdict(self)
        payload['status'] = self.status.value
        payload['artifacts'] = {k: str(v) for k, v in self.artifacts.items()}
        payload['checks'] = [c.as_dict() for c in self.checks]
        # The detail may hold live objects (a tree, a layout); keep only what is
        # serializable so summary.json never fails to write.
        payload['detail'] = {k: v for k, v in self.detail.items()
                             if isinstance(v, (str, int, float, bool, list, dict, type(None)))}
        return payload


class StageError(Exception):
    """Raised by a stage when it cannot do its work. Carries a readable message."""


class Stage:
    """Base class for a pipeline module.

    Subclasses set ``name`` and ``title`` and implement :meth:`execute`. Raising
    :class:`StageError` marks the stage failed with that message; any other exception
    is caught too and reported with its traceback.
    """

    name = 'stage'
    title = 'Stage'
    description = ''

    def execute(self, context, payload) -> StageResult:
        raise NotImplementedError

    # --- Helpers for subclasses ---------------------------------------------

    @property
    def log(self):
        return logging_setup.get_logger(self.name)

    def result(self, status=StageStatus.PASSED, summary='', **kwargs) -> StageResult:
        return StageResult(stage=self.name, status=status, summary=summary, **kwargs)


class Pipeline:
    """Runs stages in order, carrying one payload and reporting progress."""

    def __init__(self, stages, on_update=None):
        """
        Args:
            stages: the Stage instances, in execution order.
            on_update: called as ``on_update(stage_name, StageResult)`` whenever a
                stage starts or finishes. Used by the GUI to update a panel live.
        """
        self.stages = list(stages)
        self.on_update = on_update
        self.results: dict[str, StageResult] = {}

    def stage(self, name):
        for stage in self.stages:
            if stage.name == name:
                return stage
        raise KeyError(name)

    def _notify(self, name, result):
        self.results[name] = result
        if self.on_update:
            try:
                self.on_update(name, result)
            except Exception:  # noqa: BLE001 - a view error must not stop the run
                log.exception('stage observer raised')

    def run(self, context, payload, stages=None):
        """Run the given stages (all of them by default) and return their results.

        The run stops at the first stage that fails or is rejected. ``payload`` is
        updated in place, so a later call can continue from where this one stopped.
        """
        selected = [s for s in self.stages if stages is None or s.name in stages]
        self.results = {}
        paths = logging_setup.attach_run(context)
        logging_setup.event(
            log, 'run.start', f'run {context.run_id} started',
            run=context.run_id, scene=payload.get('scene'),
            stages=[s.name for s in selected], log_files=[str(p) for p in paths.values()])
        started = time.time()

        try:
            for stage in selected:
                if not self._run_stage(stage, context, payload):
                    break
        finally:
            total = time.time() - started
            summary = {
                'run_id': context.run_id,
                'scene': payload.get('scene'),
                'command': payload.get('command'),
                'enriched_command': payload.get('enriched_command'),
                'created_at': context.created_at.isoformat(timespec='seconds'),
                'total_seconds': round(total, 3),
                'stages': {name: result.as_dict() for name, result in self.results.items()},
            }
            context.write_json('summary.json', summary)
            logging_setup.event(log, 'run.end', f'run {context.run_id} finished in {total:.2f}s',
                                run=context.run_id, seconds=round(total, 3),
                                statuses={n: r.status.value for n, r in self.results.items()})
            logging_setup.detach_run()

        return self.results

    def _run_stage(self, stage, context, payload):
        """Run one stage. Returns False when the run must stop."""
        logging_setup.set_stage(stage.name)
        started_at = datetime.datetime.now()
        self._notify(stage.name, StageResult(
            stage=stage.name, status=StageStatus.RUNNING,
            summary='running…', started_at=started_at.isoformat(timespec='seconds')))
        logging_setup.event(stage.log, 'stage.start', f'{stage.title} started')

        started = time.time()
        try:
            result = stage.execute(context, payload)
        except StageError as error:
            result = StageResult(stage=stage.name, status=StageStatus.FAILED,
                                 summary=str(error), error=str(error))
            stage.log.error('%s failed: %s', stage.title, error)
        except Exception as error:  # noqa: BLE001 - report, never crash the run
            result = StageResult(stage=stage.name, status=StageStatus.FAILED,
                                 summary=f'{type(error).__name__}: {error}',
                                 error=traceback.format_exc())
            stage.log.exception('%s raised', stage.title)

        result.duration_s = round(time.time() - started, 3)
        result.started_at = started_at.isoformat(timespec='seconds')
        self._notify(stage.name, result)

        logging_setup.event(
            stage.log, 'stage.end',
            f'{stage.title} {result.status.value} in {result.duration_s:.2f}s — {result.summary}',
            level=30 if result.status in TERMINAL else 20,
            status=result.status.value, seconds=result.duration_s,
            artifacts={k: str(v) for k, v in result.artifacts.items()})
        logging_setup.set_stage(None)

        return result.status not in TERMINAL
