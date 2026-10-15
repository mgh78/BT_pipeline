"""Logging for the whole pipeline: one logger per module, one log set per run.

Three things happen to every log record:

1. It goes to the console (INFO and above) and to the global rotating files in
   ``data/logs/`` - ``debug.log``, ``info.log`` and ``error.log``. The last one alone
   tells you what has ever broken, across all runs.
2. While a run is active it also goes to that run's own directory: ``run.log`` holds
   every module together in order, and ``<module>.log`` holds one module on its own.
3. It is appended to ``events.jsonl`` as a single JSON object, so a run can be read
   back by a program rather than by eye.

Every record carries the active ``run_id`` and ``stage`` automatically, which is what
makes a single run traceable from the typed command to the rendered tree.

Use it like this::

    from core import logging_setup

    log = logging_setup.get_logger('generator')
    log.info('asking the model')
    logging_setup.event(log, 'llm.response', 'model replied', tokens=812, seconds=2.4)
"""

import collections
import datetime
import json
import logging
import logging.handlers
import threading
from pathlib import Path

import config

ROOT_LOGGER_NAME = 'pipeline'

# Every module that logs. Each one gets its own file inside a run directory.
MODULES = ('pipeline', 'scene', 'command', 'enrichment', 'generator', 'tester', 'graph', 'gui')

FILE_FORMAT = ('%(asctime)s | %(levelname)-8s | %(module_name)-10s | %(run_id)-24s | '
               '%(stage)-10s | %(filename)s:%(lineno)d | %(message)s')
CONSOLE_FORMAT = '%(levelname)-7s %(module_name)-10s %(message)s'

# The run the pipeline is currently executing. Stages run one at a time, so a single
# module-level value is enough and is simpler than threading a context through.
_active_run_id = '-'
_active_stage = '-'

_configured = False
_run_handlers: list[logging.Handler] = []
_lock = threading.Lock()


# --- Record decoration -------------------------------------------------------

class _ContextFilter(logging.Filter):
    """Attach the module name, the active run and the active stage to every record."""

    def filter(self, record):
        record.module_name = record.name.split('.')[-1]
        if not hasattr(record, 'run_id'):
            record.run_id = _active_run_id
        if not hasattr(record, 'stage'):
            record.stage = _active_stage
        if not hasattr(record, 'event'):
            record.event = ''
        return True


class _ModuleFilter(logging.Filter):
    """Keep only the records of one module, for that module's own log file."""

    def __init__(self, module):
        super().__init__()
        self.module = module

    def filter(self, record):
        return record.name.split('.')[-1] == self.module


class JsonlHandler(logging.Handler):
    """Write one JSON object per record, for machine-readable run inspection."""

    def __init__(self, path, level=logging.DEBUG):
        super().__init__(level)
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._stream = open(self.path, 'a', encoding='utf-8')

    def emit(self, record):
        try:
            payload = {
                'ts': datetime.datetime.fromtimestamp(record.created).isoformat(timespec='milliseconds'),
                'level': record.levelname,
                'module': getattr(record, 'module_name', record.name),
                'run_id': getattr(record, 'run_id', '-'),
                'stage': getattr(record, 'stage', '-'),
                'event': getattr(record, 'event', ''),
                'message': record.getMessage(),
                'source': f'{record.filename}:{record.lineno}',
            }
            data = getattr(record, 'data', None)
            if data:
                payload['data'] = data
            if record.exc_info:
                payload['exception'] = self.format(record)
            self._stream.write(json.dumps(payload, ensure_ascii=False, default=str) + '\n')
            self._stream.flush()
        except Exception:  # noqa: BLE001 - logging must never raise into the caller
            self.handleError(record)

    def close(self):
        try:
            self._stream.close()
        finally:
            super().close()


class GuiLogBuffer(logging.Handler):
    """Keep recent records in memory and notify the GUI so it can show them live."""

    def __init__(self, capacity):
        super().__init__(logging.DEBUG)
        self.records = collections.deque(maxlen=capacity)
        self._subscribers = []

    def emit(self, record):
        entry = {
            'ts': datetime.datetime.fromtimestamp(record.created).strftime('%H:%M:%S.%f')[:-3],
            'level': record.levelname,
            'module': getattr(record, 'module_name', record.name),
            'stage': getattr(record, 'stage', '-'),
            'run_id': getattr(record, 'run_id', '-'),
            'message': record.getMessage(),
        }
        self.records.append(entry)
        for subscriber in list(self._subscribers):
            try:
                subscriber(entry)
            except Exception:  # noqa: BLE001 - a broken view must not break logging
                pass

    def subscribe(self, callback):
        self._subscribers.append(callback)

    def snapshot(self, module=None, level=None):
        """Return the buffered records, optionally filtered by module or level."""
        entries = list(self.records)
        if module and module != 'all':
            entries = [e for e in entries if e['module'] == module]
        if level and level != 'all':
            threshold = logging.getLevelName(level.upper())
            if isinstance(threshold, int):
                entries = [e for e in entries
                           if logging.getLevelName(e['level']) >= threshold]
        return entries


gui_buffer = GuiLogBuffer(config.GUI_LOG_BUFFER)


# --- Setup -------------------------------------------------------------------

def _rotating(path, level):
    handler = logging.handlers.TimedRotatingFileHandler(
        path, when='midnight', backupCount=config.LOG_BACKUP_COUNT, encoding='utf-8')
    handler.setLevel(level)
    handler.setFormatter(logging.Formatter(FILE_FORMAT))
    return handler


def configure():
    """Install the console, the global files and the GUI buffer. Safe to call twice."""
    global _configured
    with _lock:
        if _configured:
            return
        config.LOG_DIR.mkdir(parents=True, exist_ok=True)

        root = logging.getLogger(ROOT_LOGGER_NAME)
        root.setLevel(logging.DEBUG)
        root.propagate = False
        root.handlers.clear()
        root.addFilter(_ContextFilter())

        console = logging.StreamHandler()
        console.setLevel(getattr(logging, config.CONSOLE_LOG_LEVEL))
        console.setFormatter(logging.Formatter(CONSOLE_FORMAT))
        root.addHandler(console)

        root.addHandler(_rotating(config.LOG_DIR / 'debug.log', logging.DEBUG))
        root.addHandler(_rotating(config.LOG_DIR / 'info.log', logging.INFO))
        root.addHandler(_rotating(config.LOG_DIR / 'error.log', logging.ERROR))
        root.addHandler(gui_buffer)

        # The filter must sit on the handlers too: a filter on a logger is not applied
        # to records that reach it from a child logger.
        for handler in root.handlers:
            handler.addFilter(_ContextFilter())

        _configured = True


def get_logger(module):
    """Return the logger of one module, for example ``get_logger('tester')``."""
    configure()
    return logging.getLogger(f'{ROOT_LOGGER_NAME}.{module}')


# --- Run-scoped logging ------------------------------------------------------

def attach_run(run_context):
    """Start writing this run's own log files. Returns the paths that were opened."""
    global _active_run_id
    configure()
    detach_run()

    root = logging.getLogger(ROOT_LOGGER_NAME)
    _active_run_id = run_context.run_id
    paths = {}

    combined = logging.FileHandler(run_context.path('run.log'), encoding='utf-8')
    combined.setLevel(getattr(logging, config.FILE_LOG_LEVEL))
    combined.setFormatter(logging.Formatter(FILE_FORMAT))
    combined.addFilter(_ContextFilter())
    root.addHandler(combined)
    _run_handlers.append(combined)
    paths['run.log'] = run_context.path('run.log')

    for module in MODULES:
        path = run_context.path(f'logs/{module}.log')
        handler = logging.FileHandler(path, encoding='utf-8')
        handler.setLevel(logging.DEBUG)
        handler.setFormatter(logging.Formatter(FILE_FORMAT))
        handler.addFilter(_ContextFilter())
        handler.addFilter(_ModuleFilter(module))
        root.addHandler(handler)
        _run_handlers.append(handler)
        paths[f'{module}.log'] = path

    events = JsonlHandler(run_context.path('events.jsonl'))
    events.addFilter(_ContextFilter())
    root.addHandler(events)
    _run_handlers.append(events)
    paths['events.jsonl'] = run_context.path('events.jsonl')

    return paths


def detach_run():
    """Close this run's log files and go back to global logging only."""
    global _active_run_id, _active_stage
    root = logging.getLogger(ROOT_LOGGER_NAME)
    while _run_handlers:
        handler = _run_handlers.pop()
        root.removeHandler(handler)
        handler.close()
    _active_run_id = '-'
    _active_stage = '-'


def set_stage(stage):
    """Name the stage that later records belong to."""
    global _active_stage
    _active_stage = stage or '-'


# --- Structured events -------------------------------------------------------

def event(logger, name, message, level=logging.INFO, **data):
    """Log a named event with structured data attached.

    The message is what you read in ``run.log``; ``name`` and ``data`` are what you
    query in ``events.jsonl``.
    """
    # stacklevel=2 so the record points at the caller, not at this helper.
    logger.log(level, message, extra={'event': name, 'data': data or None}, stacklevel=2)
