"""The generation loop: generator, syntax check and semantic judge.

Nothing here waits for a person. The generator always returns a tree, taking the most
reasonable reading of whatever it is given; the syntax check decides whether the code
can run; the judge decides whether the tree means what the user asked for. A tree that
shakes an open test tube is no longer prevented - it is written, caught by the judge,
and repaired.

This module holds the pieces that join them: the judgement form and its validation, the
two message formats, the feedback texts, and :func:`run_generation_loop`, which runs the
three stages until a tree is accepted or a cap is reached.

The loop takes plain callables rather than stages, so it can be driven by the real
pipeline or by scripted replies in a test.
"""

import json
import re

import config
from core import logging_setup

log = logging_setup.get_logger('judge')

# --- The judgement form -------------------------------------------------------

# Passed to the API as a structured output schema when the model supports it. The model
# writes the fields in the order they appear here, so ``analysis`` comes first: the judge
# works through its checks before it commits to a verdict. ``errors`` are free text: the
# judge names each problem in its own words, with no fixed set of categories.
JUDGE_SCHEMA = {
    'type': 'object',
    'properties': {
        'analysis': {'type': 'string'},
        'verdict': {'type': 'string', 'enum': ['accept', 'reject']},
        'errors': {'type': 'array', 'items': {'type': 'string'}},
        'reason': {'type': 'string'},
    },
    'required': ['analysis', 'verdict', 'errors', 'reason'],
    'additionalProperties': False,
}

RESPONSE_FORMAT = {
    'type': 'json_schema',
    'json_schema': {'name': 'judgement_form', 'strict': True, 'schema': JUDGE_SCHEMA},
}

# How a run can end. Nobody is ever asked anything, so a run never waits.
# 'no_judge' is the baseline: the judge was switched off, so the first tree that
# passes the syntax check is the result and nothing judged it.
FINAL_STATUSES = ('accepted', 'no_judge', 'failed_judge_cap', 'failed_syntax_cap',
                  'judge_error', 'error')

# Sent back when the generator answered with prose instead of a tree.
NO_CODE_PROBLEM = ('Your reply contained no create_behavior_tree() code block. '
                   'Return the tree.')

_FENCE = re.compile(r'^```(?:json)?\s*(.*?)\s*```$', re.DOTALL)


def parse_judgement(text):
    """Return the judge's form as a dict, or raise ValueError saying what is wrong.

    Applied to every reply, including a structured one: a schema can enforce the shape
    but not that an accepted tree lists no errors, or that a rejection gives a reason.
    The analysis is kept with the form but is never part of the feedback the tree's
    author receives: that stays the errors and the reason (``reviewer_problems``).
    """
    cleaned = text.strip()
    fenced = _FENCE.match(cleaned)
    if fenced:
        cleaned = fenced.group(1)
    try:
        form = json.loads(cleaned)
    except json.JSONDecodeError as error:
        raise ValueError(f'the reply is not valid JSON ({error})') from error
    if not isinstance(form, dict) or set(form) != {'analysis', 'verdict', 'errors', 'reason'}:
        raise ValueError('the form must have exactly the keys analysis, verdict, errors '
                         'and reason')

    analysis, verdict = form['analysis'], form['verdict']
    errors, reason = form['errors'], form['reason']
    if not isinstance(analysis, str) or not analysis.strip():
        raise ValueError('analysis must be a non-empty string')
    if verdict not in ('accept', 'reject'):
        raise ValueError(f'verdict must be "accept" or "reject", not {verdict!r}')
    if (not isinstance(errors, list)
            or any(not isinstance(e, str) or not e.strip() for e in errors)):
        raise ValueError(f'errors must be a list of non-empty phrases, got {errors!r}')
    if not isinstance(reason, str):
        raise ValueError('reason must be a string')
    if verdict == 'accept' and errors:
        raise ValueError('an accepted tree cannot have errors')
    if verdict == 'reject' and (not errors or not reason.strip()):
        raise ValueError('a rejection needs at least one error and a reason')

    return {'analysis': analysis.strip(), 'verdict': verdict,
            'errors': list(dict.fromkeys(e.strip() for e in errors)),
            'reason': reason.strip()}


def form_sentences(form):
    """The problems the judge listed, in the judge's own words."""
    return list(form.get('errors', []))


# --- What the judge is shown --------------------------------------------------

def outline_for_judge(node, depth=0):
    """The built tree as the judge reads it: action type and arguments on every line.

    Composites show their type and name; actions show their type, their arguments and
    their name in brackets. The judge is told to trust the arguments, not the names,
    which is why the tester's ``_as_text`` is not reused - it shows names only.
    """
    indent = '    ' * depth
    kind = type(node).__name__
    if kind in ('Sequence', 'Selector'):
        lines = [f'{indent}{kind} [{node.name}]']
        lines += [outline_for_judge(child, depth + 1) for child in node.children]
        return '\n'.join(lines)
    arguments = ', '.join(f'{key}={json.dumps(value)}'
                          for key, value in (getattr(node, 'arguments', None) or {}).items())
    return f'{indent}{kind}({arguments}) [{node.name}]'


def judge_message(original_command, rewritten_command, outline):
    """The user message for one judge call.

    The judge is given the command the user typed, because the rewritten one was
    produced by another model and may itself be the error.
    """
    parts = [f'ORIGINAL COMMAND: {original_command}']
    if rewritten_command and rewritten_command.strip().lower() != original_command.strip().lower():
        parts.append(f'REWRITTEN COMMAND: {rewritten_command}')
    parts += ['BEHAVIOR TREE:', outline]
    return '\n'.join(parts)


# --- What the generator is shown ----------------------------------------------

def parse_generator_reply(answer, extract_code):
    """Return ``('code', code)`` or ``('no_code', text)``.

    The generator is told to answer with a tree and nothing else, so prose is a failed
    attempt rather than a question: the caller sends it back and counts it toward the
    syntax cap.
    """
    code = extract_code(answer)
    if code is not None:
        return 'code', code
    return 'no_code', answer.strip()


def generator_message(command, previous_code=None, problems=None):
    """The user message for one generator call.

    ``problems`` is the text from :func:`syntax_problems`, :func:`reviewer_problems` or
    :data:`NO_CODE_PROBLEM`. A tree comes with it whenever there was one to send back.
    """
    parts = [f'COMMAND: {command}']
    if previous_code:
        parts += ['PREVIOUS TREE:', previous_code]
    if problems:
        parts.append(problems)
    return '\n'.join(parts)


def syntax_problems(checks):
    """The blocking checks of a failed syntax test, written for the generator."""
    lines = ['SYNTAX CHECK ERRORS:']
    for check in checks:
        if check.blocking:
            # Most tester messages already name their line; add it only when missing.
            where = (f' (line {check.line})'
                     if check.line and f'line {check.line}' not in check.message else '')
            lines.append(f'- {check.title}: {check.message}{where}')
    return '\n'.join(lines)


def reviewer_problems(form):
    """A rejected judgement form, written for the generator."""
    problems = '; '.join(form_sentences(form))
    return f'REVIEWER FINDINGS:\nProblems: {problems}.\nReason: {form["reason"]}'


# --- The loop -----------------------------------------------------------------

def run_generation_loop(command, original_command, rewritten_command,
                        generate, syntax_check, judge, extract_code,
                        clock=None, on_update=None):
    """Run generator, syntax check and judge until a tree is accepted.

    Nothing in here waits for a person: the generator always returns a tree, and the
    judge is the only thing that decides whether it is right.

    Without a judge (``judge=None``) this is the baseline and there is no loop at all:
    one generator call, one syntax check, and the tree that came out.

    Args:
        command: the text the generator works from - the rewritten command when
            enrichment ran, otherwise the typed one.
        original_command: what the user typed. The judge is always given this.
        rewritten_command: the enriched command, or None.
        generate: ``generate(message, attempt) -> raw reply``.
        syntax_check: ``syntax_check(code, attempt) -> (passed, tree_or_None, checks)``.
        judge: ``judge(message, attempt, call) -> raw reply``, or None for the
            baseline. With no judge there is nothing to repair towards, so the
            baseline is a single pass: one generator call, one syntax check, and
            whatever came out.
        extract_code: ``BTGenerator.extract_code``.
        clock: time source, for tests.
        on_update: optional ``on_update(record, attempt)`` after every step, so the
            window can follow a run that is still going.

    Returns:
        dict: the final status, every attempt, the counters and the timestamps. The
        accepted tree, when there is one, is under ``accepted_tree``.
    """
    import time

    clock = clock or time.time
    record = {
        'status': None, 'attempts': [], 'accepted_tree': None,
        'counts': {'generator_calls': 0, 'syntax_failures': 0,
                   'judge_calls': 0, 'judge_rejections': 0, 'judge_format_errors': 0},
        'times': {'loop_started': clock(), 'first_valid_tree': None, 'accepted': None},
    }
    counts = record['counts']

    def notify(attempt=None):
        if on_update:
            try:
                on_update(record, attempt)
            except Exception:  # noqa: BLE001 - a view error must not stop the run
                log.exception('loop observer raised')

    def finish(status):
        record['status'] = status
        log.info('loop finished: %s after %d generator call(s)',
                 status, counts['generator_calls'])
        notify()
        return record

    previous_code = problems = None
    while True:
        message = generator_message(command, previous_code, problems)
        counts['generator_calls'] += 1
        attempt = {'n': counts['generator_calls'], 'generator_message': message,
                   'kind': None, 'syntax_passed': None, 'judge_form': None,
                   'ground_truth': None}
        record['attempts'].append(attempt)
        notify(attempt)

        reply = generate(message, attempt)
        attempt['generator_reply'] = reply
        kind, body = parse_generator_reply(reply, extract_code)
        attempt['kind'] = kind
        notify(attempt)

        # Prose instead of a tree. Ask for the tree again; it costs an attempt.
        if kind == 'no_code':
            counts['syntax_failures'] += 1
            attempt['syntax_passed'] = False
            attempt['syntax_errors'] = NO_CODE_PROBLEM
            previous_code, problems = None, NO_CODE_PROBLEM
            log.warning('the generator replied without a code block (%d of %d)',
                        counts['syntax_failures'], config.SYNTAX_FAILURE_LIMIT)
            notify(attempt)
            # The baseline has nothing to repair towards, so it does not try again.
            if judge is None or counts['syntax_failures'] >= config.SYNTAX_FAILURE_LIMIT:
                return finish('failed_syntax_cap')
            continue

        # Syntax check.
        attempt['code'] = body
        passed, tree, checks = syntax_check(body, attempt)
        attempt['syntax_passed'] = passed
        notify(attempt)
        if not passed:
            counts['syntax_failures'] += 1
            previous_code, problems = body, syntax_problems(checks)
            attempt['syntax_errors'] = problems
            log.info('syntax failure %d of %d',
                     counts['syntax_failures'], config.SYNTAX_FAILURE_LIMIT)
            if judge is None or counts['syntax_failures'] >= config.SYNTAX_FAILURE_LIMIT:
                return finish('failed_syntax_cap')
            continue
        if record['times']['first_valid_tree'] is None:
            record['times']['first_valid_tree'] = clock()

        # Baseline: no judge, so nothing decides whether to try again. One tree is the
        # whole run - generate, check it can run, draw it.
        if judge is None:
            attempt['outline'] = outline_for_judge(tree)
            record['accepted_tree'] = tree
            record['times']['accepted'] = clock()
            log.info('baseline run: the tree was not judged')
            return finish('no_judge')

        # Semantic judge. A fresh call for every tree: it never sees earlier verdicts.
        outline = outline_for_judge(tree)
        judge_input = judge_message(original_command, rewritten_command, outline)
        attempt.update({'outline': outline, 'judge_message': judge_input,
                        'judge_replies': []})
        message_to_judge = judge_input
        for call in range(1 + config.JUDGE_FORMAT_RETRIES):
            counts['judge_calls'] += 1
            raw = judge(message_to_judge, attempt, call)
            attempt['judge_replies'].append(raw)
            try:
                attempt['judge_form'] = parse_judgement(raw)
                break
            except ValueError as error:
                counts['judge_format_errors'] += 1
                log.warning('the judge did not answer with a valid form: %s', error)
                message_to_judge = (f'{judge_input}\n\nYour previous answer was not a valid '
                                    f'judgement form: {error}. Answer with only the JSON '
                                    f'object.')
        form = attempt['judge_form']
        notify(attempt)
        if form is None:
            # Never accept a tree because the judge failed.
            return finish('judge_error')
        if form['verdict'] == 'accept':
            record['accepted_tree'] = tree
            record['times']['accepted'] = clock()
            log.info('the judge accepted the tree')
            return finish('accepted')

        counts['judge_rejections'] += 1
        log.info('the judge rejected the tree (%s): %s',
                 ', '.join(form['errors']), form['reason'])
        if counts['judge_rejections'] >= config.JUDGE_REJECTION_LIMIT:
            return finish('failed_judge_cap')
        previous_code, problems = body, reviewer_problems(form)
