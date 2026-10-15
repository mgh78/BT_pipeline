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

# Which run status counts as a success for the stage's own state.
SUCCESS = 'accepted'

# What to tell the user for each way a run can end.
STATUS_TEXT = {
    'accepted': 'the judge accepted the tree',
    'failed_judge_cap': 'the judge rejected every tree',
    'failed_syntax_cap': 'no tree passed the syntax check',
    'failed_clarification_cap': 'the generator kept asking questions',
    'no_answer': 'the question was not answered',
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

        generator = BTGenerator(model=payload.get('generation_model'))
        judge = SemanticJudge(model=payload.get('judge_model'))
        tester = SyntaxTestStage()
        artifacts = {}

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

        ask_user = self._clarification_source(payload)

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
            judge=ask_judge,
            ask_user=ask_user,
            extract_code=generator.extract_code,
            on_update=on_update)

        payload['loop_record'] = record
        payload['generator'] = generator.describe()
        payload['judge'] = judge.describe()
        result = self._report(context, payload, record, artifacts)
        payload['loop_summary'] = loop_summary(record, payload)
        return result

    # --- Clarification ---------------------------------------------------

    def _clarification_source(self, payload):
        """Return ``ask_user(question)``.

        The window supplies a callable that shows the question and waits. A scripted
        run supplies a list of answers instead; when it runs out, nobody answers and
        the run ends as ``no_answer``.
        """
        provider = payload.get('clarification_provider')
        if callable(provider):
            return provider

        answers = list(payload.get('clarification_answers') or [])
        payload.setdefault('clarification_answers_used', [])

        def from_list(question):
            self.log.info('clarification asked: %s', question)
            if not answers:
                self.log.warning('nobody is there to answer the question')
                return None
            answer = answers.pop(0)
            payload['clarification_answers_used'].append(answer)
            self.log.info('scripted answer: %s', answer)
            return answer

        return from_list

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

        if record['clarifications']:
            artifacts['clarifications'] = context.write_json(
                'clarifications.json',
                [{'question': q, 'answer': a} for q, a in record['clarifications']])

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

        summary = STATUS_TEXT.get(status, status)
        if status == SUCCESS:
            summary = (f'accepted after {len(attempts)} attempt'
                       f'{"s" if len(attempts) != 1 else ""}')
        else:
            summary = f'{status} — {STATUS_TEXT.get(status, "")}'

        detail = {
            'status': status,
            'attempts': len(attempts),
            'command sent': payload.get('generator_input'),
            **{key.replace('_', ' '): value for key, value in counts.items()},
            'generator': f'{payload["generator"]["model"]} '
                         f'(temperature {payload["generator"]["temperature"]})',
            'judge': f'{payload["judge"]["model"]} '
                     f'(temperature {payload["judge"]["temperature"]}'
                     f'{", structured output" if payload["judge"]["structured_output"] else ""})',
        }
        for attempt in attempts:
            detail[f'attempt {attempt["n"]}'] = self._attempt_line(attempt)

        return self.result(
            StageStatus.PASSED if status == SUCCESS else StageStatus.FAILED,
            summary=summary, detail=detail, artifacts=artifacts,
            error=None if status == SUCCESS else STATUS_TEXT.get(status, status))

    @staticmethod
    def _attempt_line(attempt):
        if attempt['kind'] == 'clarify':
            question = attempt.get('question', '')
            answered = attempt.get('answer')
            return (f'asked: {question}'
                    + (f'  →  answered: {answered}' if answered else '  →  unanswered'))
        if attempt.get('syntax_passed') is False:
            return 'tree written, syntax check failed'
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
        'models': {'generator': payload.get('generator'), 'judge': payload.get('judge')},
        'caps': {
            'clarification_limit': config.CLARIFICATION_LIMIT,
            'syntax_failure_limit': config.SYNTAX_FAILURE_LIMIT,
            'judge_rejection_limit': config.JUDGE_REJECTION_LIMIT,
            'judge_format_retries': config.JUDGE_FORMAT_RETRIES,
        },
        'times': {
            't_command': _moment(payload.get('t_command')),
            't_first_valid_tree': _moment(record['times']['first_valid_tree']),
            't_accepted': _moment(record['times']['accepted']),
        },
        'clarifications': [{'question': q, 'answer': a}
                           for q, a in record['clarifications']],
        'attempts': [
            {
                'n': attempt['n'],
                'kind': attempt['kind'],
                'syntax_passed': attempt.get('syntax_passed'),
                'judge_form': attempt.get('judge_form'),
                'question': attempt.get('question'),
                'answer': attempt.get('answer'),
                'format_warning': attempt.get('format_warning'),
                'ground_truth': attempt.get('ground_truth'),
            }
            for attempt in record['attempts']
        ],
    }
