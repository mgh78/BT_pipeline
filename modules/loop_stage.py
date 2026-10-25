"""The pipeline stage that runs the generation loop.

Scene, Command and Enrichment stay a straight sequence; this one stage replaces what
used to be Generator → Syntax check, and adds the semantic judge and the repairs:

    Scene → Command → Enrichment → [ Generator → Syntax check → Judge ] → Graph

It owns the artifacts of every attempt, so nothing a run produces is overwritten when
a tree is sent back for repair.
"""

import datetime

import config
from core import logging_setup
from core.pipeline import Stage, StageError, StageStatus
from modules import loop
from modules.generator import BTGenerator, as_module
from modules.judge import SemanticJudge, form_summary
from modules.tester import SyntaxTestStage, spill_label

# Which run statuses count as a success for the stage's own state.
SUCCESS = {'accepted', 'no_judge'}

# What to tell the user for each way a run can end.
STATUS_TEXT = {
    'accepted': 'the judge accepted the tree',
    'no_judge': 'baseline run — the tree was not judged',
    'failed_judge_cap': 'the judge rejected every tree',
    'failed_syntax_cap': 'no tree passed the syntax check',
    'judge_error': 'the judge never returned a valid form',
    'error': 'the run stopped with an error',
}


class GenerationLoopStage(Stage):
    """Generate, check and judge until a tree is accepted or a cap is reached."""

    name = 'loop'
    title = 'Generation loop'
    description = 'Generate a tree, check it, judge it, and repair it until it is accepted.'

    def execute(self, context, payload):
        scene = payload.get('scene_object')
        if scene is None:
            raise StageError('Run the scene stage first.')

        original = (payload.get('command') or '').strip()
        rewritten = (payload.get('enriched_command') or '').strip() or None
        command = rewritten or original
        if not command:
            raise StageError('There is no command to generate a tree from.')
        payload['generator_input'] = command

        generator = BTGenerator(
            model=payload.get('generation_model'),
            reasoning_effort=payload.get('generation_reasoning_effort'))
        tester = SyntaxTestStage()
        artifacts = {}

        # With the judge switched off this is the baseline: a syntax failure is still sent
        # back to the generator, but nothing judges the tree that finally runs.
        judge_enabled = payload.get('judge_enabled')
        if judge_enabled is None:
            judge_enabled = config.JUDGE_ENABLED
        judge = (SemanticJudge(model=payload.get('judge_model'),
                               reasoning_effort=payload.get('judge_reasoning_effort'))
                 if judge_enabled else None)
        if not judge_enabled:
            self.log.info('baseline run: the judge is switched off')

        # --- The four things the loop needs ---------------------------------

        def attempt_folder(attempt):
            return f'attempts/{attempt["n"]:02d}'

        def generate(message, attempt):
            folder = attempt_folder(attempt)
            return generator.ask(message, scene, context,
                                 tag=f'{folder}/generation')

        def syntax_check(code, attempt):
            folder = attempt_folder(attempt)
            checks, tree, analysis = tester.check(code, scene)
            passed = tester.passed(checks)
            # Kept for the window, which lets you look at any attempt, not only the
            # accepted one.
            attempt['checks'] = checks
            attempt['tree'] = tree

            artifacts[f'attempt {attempt["n"]} tree'] = context.write_text(
                f'{folder}/create_behavior_tree.py', code + '\n')
            context.write_json(f'{folder}/tester_report.json', {
                'passed': passed,
                'checks': [check.as_dict() for check in checks],
            })
            # An automatic label for later analysis only. It is never shown to the
            # generator or the judge and never changes a status.
            label = spill_label(analysis, scene)
            if label is not None:
                context.write_json(f'{folder}/analysis_labels.json', label)
            return passed, tree, checks

        def ask_judge(message, attempt, call):
            folder = attempt_folder(attempt)
            if call == 0:
                context.write_text(f'{folder}/judge_outline.txt', attempt['outline'])
            return judge.ask(message, scene, context,
                             tag=f'{folder}/judge/{call + 1:02d}')

        # --- Run it ---------------------------------------------------------

        def on_update(record, attempt):
            self._write_attempt_form(context, attempt, artifacts)
            payload['loop_record'] = record
            observer = payload.get('on_loop_update')
            if observer:
                observer(record, attempt)

        record = loop.run_generation_loop(
            command=command,
            original_command=original,
            rewritten_command=rewritten,
            generate=generate,
            syntax_check=syntax_check,
            judge=ask_judge if judge_enabled else None,
            extract_code=generator.extract_code,
            on_update=on_update)

        payload['loop_record'] = record
        payload['generator'] = generator.describe()
        payload['judge'] = judge.describe() if judge else {'enabled': False}
        payload['judge_enabled'] = bool(judge_enabled)
        result = self._report(context, payload, record, artifacts)
        payload['loop_summary'] = loop_summary(record, payload)
        return result

    # --- Artifacts and the result ----------------------------------------

    @staticmethod
    def _write_attempt_form(context, attempt, artifacts):
        """Save an attempt's judgement form as soon as it exists."""
        if not attempt or attempt.get('judge_form') is None:
            return
        folder = f'attempts/{attempt["n"]:02d}'
        path = context.write_json(f'{folder}/judge_form.json', attempt['judge_form'])
        artifacts[f'attempt {attempt["n"]} judge form'] = path

    def _report(self, context, payload, record, artifacts):
        status = record['status']
        counts = record['counts']
        attempts = record['attempts']

        accepted = record['accepted_tree']
        if accepted is not None:
            last = attempts[-1]
            payload['tree'] = accepted
            payload['code'] = last['code']
            payload['answer'] = last['generator_reply']
            artifacts['behavior tree'] = context.write_text(
                'bt.py', as_module(last['code'], payload))
            artifacts['function only'] = context.write_text(
                'create_behavior_tree.py', last['code'] + '\n')

        # What the window shows when no attempt is selected: the last tree that was
        # written, and the checks it got.
        for attempt in reversed(attempts):
            if attempt.get('code'):
                payload.setdefault('code', attempt['code'])
                payload['checks'] = attempt.get('checks', [])
                break
        else:
            payload['checks'] = []
            if attempts:
                payload['answer'] = attempts[-1].get('generator_reply')

        for attempt in attempts:
            self.log.info('attempt %d: %s%s%s', attempt['n'], attempt['kind'],
                          '' if attempt.get('syntax_passed') is None
                          else f', syntax {"passed" if attempt["syntax_passed"] else "failed"}',
                          '' if attempt.get('judge_form') is None
                          else f', judge {form_summary(attempt["judge_form"])}')

        if status == 'accepted':
            summary = (f'accepted after {len(attempts)} attempt'
                       f'{"s" if len(attempts) != 1 else ""}')
        elif status == 'no_judge':
            summary = 'baseline — tree built, not judged'
        else:
            summary = f'{status} — {STATUS_TEXT.get(status, "")}'

        detail = {
            'status': status,
            'attempts': len(attempts),
            'command sent': payload.get('generator_input'),
            **{key.replace('_', ' '): value for key, value in counts.items()},
            'generator': f'{payload["generator"]["model"]} '
                         f'(temperature {payload["generator"]["temperature"]})',
            'judge': (f'{payload["judge"]["model"]} '
                      f'(temperature {payload["judge"]["temperature"]}'
                      f'{", structured output" if payload["judge"]["structured_output"] else ""})'
                      if payload.get('judge_enabled')
                      else 'switched off — this is a baseline run'),
        }
        for attempt in attempts:
            detail[f'attempt {attempt["n"]}'] = self._attempt_line(
                attempt, payload.get('judge_enabled', True))

        succeeded = status in SUCCESS
        return self.result(
            StageStatus.PASSED if succeeded else StageStatus.FAILED,
            summary=summary, detail=detail, artifacts=artifacts,
            error=None if succeeded else STATUS_TEXT.get(status, status))

    @staticmethod
    def _attempt_line(attempt, judged=True):
        if attempt['kind'] == 'no_code':
            return ('no code in the reply' if not judged
                    else 'no code in the reply, asked again')
        if attempt.get('syntax_passed') is False:
            return 'tree written, syntax check failed'
        if not judged:
            return 'tree written, syntax check passed, not judged'
        return f'tree written, syntax check passed, {form_summary(attempt.get("judge_form"))}'


def _moment(seconds):
    """A loop timestamp as a readable string, or None when it never happened."""
    if not seconds:
        return None
    return datetime.datetime.fromtimestamp(seconds).isoformat(timespec='milliseconds')


def loop_summary(record, payload):
    """The part of ``summary.json`` that describes the loop.

    ``ground_truth`` is left null on purpose: it is filled in by hand with "correct" or
    "faulty" until the simulation exists, and without it the judge cannot be evaluated.
    """
    if record is None:
        return None
    return {
        'status': record['status'],
        'counts': record['counts'],
        'enrichment': {
            'on': bool(payload.get('enrichment_on')),
            **(payload.get('enrichment') or {}),
        },
        'judge_enabled': bool(payload.get('judge_enabled')),
        'models': {'generator': payload.get('generator'), 'judge': payload.get('judge')},
        'caps': {
            'syntax_failure_limit': config.SYNTAX_FAILURE_LIMIT,
            'judge_rejection_limit': config.JUDGE_REJECTION_LIMIT,
            'judge_format_retries': config.JUDGE_FORMAT_RETRIES,
        },
        'times': {
            't_command': _moment(payload.get('t_command')),
            't_first_valid_tree': _moment(record['times']['first_valid_tree']),
            't_accepted': _moment(record['times']['accepted']),
        },
        'attempts': [
            {
                'n': attempt['n'],
                'kind': attempt['kind'],
                'syntax_passed': attempt.get('syntax_passed'),
                'judge_form': attempt.get('judge_form'),
                'ground_truth': attempt.get('ground_truth'),
            }
            for attempt in record['attempts']
        ],
    }
