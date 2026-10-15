"""Reference implementation for the semantic-judge update. Adapt it, keep the behaviour.

Contents:
  ERROR_CODES, JUDGE_SCHEMA, parse_judgement()   the judgement form and its validation
  outline_for_judge(), judge_message()          what the judge is shown
  parse_generator_reply(), generator_message()  what the generator is shown and returns
  syntax_problems(), reviewer_problems()        feedback sent back to the generator
  run_generation_loop()                         clarification / syntax / judge loop with caps

Tested against tester.py and scene.py from the current pipeline: the prompt examples pass
the syntax check, the outlines match the judge prompt verbatim, and ten loop cases with
scripted model replies end in the expected status (see PIPELINE_UPDATE.md, section 6).
The functions take plain callables so they can be wired into core.pipeline's stages and
tested with scripted replies instead of API calls.
"""

import json
import re

# --- Judgement form -----------------------------------------------------------

# Codes the judge answers with, and the judgement-form sentence each one stands for.
ERROR_CODES = {
    'goal_not_achieved': 'The tree does not achieve the requested goal',
    'missing_action': 'A required action is missing',
    'wrong_order': 'Actions are in the wrong order',
    'wrong_object_or_location': 'A wrong object or location is used',
    'missing_precondition': 'A necessary precondition or check is missing',
    'not_feasible': 'The task is not feasible for the robot',
}

# For OpenAI structured outputs:
# response_format={'type': 'json_schema',
#                  'json_schema': {'name': 'judgement_form', 'strict': True,
#                                  'schema': JUDGE_SCHEMA}}
JUDGE_SCHEMA = {
    'type': 'object',
    'properties': {
        'verdict': {'type': 'string', 'enum': ['accept', 'reject']},
        'errors': {'type': 'array', 'items': {'type': 'string', 'enum': list(ERROR_CODES)}},
        'reason': {'type': 'string'},
    },
    'required': ['verdict', 'errors', 'reason'],
    'additionalProperties': False,
}

_FENCE = re.compile(r'^```(?:json)?\s*(.*?)\s*```$', re.DOTALL)


def parse_judgement(text):
    """Return the judge's form as a dict, or raise ValueError saying what is wrong."""
    cleaned = text.strip()
    fenced = _FENCE.match(cleaned)
    if fenced:
        cleaned = fenced.group(1)
    try:
        form = json.loads(cleaned)
    except json.JSONDecodeError as error:
        raise ValueError(f'the reply is not valid JSON ({error})') from error
    if not isinstance(form, dict) or set(form) != {'verdict', 'errors', 'reason'}:
        raise ValueError('the form must have exactly the keys verdict, errors and reason')

    verdict, errors, reason = form['verdict'], form['errors'], form['reason']
    if verdict not in ('accept', 'reject'):
        raise ValueError(f'verdict must be "accept" or "reject", not {verdict!r}')
    if not isinstance(errors, list) or any(e not in ERROR_CODES for e in errors):
        raise ValueError(f'errors must be a list of known codes, got {errors!r}')
    if not isinstance(reason, str):
        raise ValueError('reason must be a string')
    if verdict == 'accept' and errors:
        raise ValueError('an accepted tree cannot have errors')
    if verdict == 'reject' and (not errors or not reason.strip()):
        raise ValueError('a rejection needs at least one error code and a reason')

    return {'verdict': verdict, 'errors': list(dict.fromkeys(errors)),
            'reason': reason.strip()}


# --- What the judge sees ------------------------------------------------------

def outline_for_judge(node, depth=0):
    """The built tree as the judge reads it: action type and arguments on every line.

    Composites show their type and name; actions show their type, their arguments and
    their name in brackets. The judge is told to trust the arguments, not the names.
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


def judge_message(original_command, rewritten_command, clarifications, outline):
    """The user message for one judge call."""
    parts = [f'ORIGINAL COMMAND: {original_command}']
    if rewritten_command and rewritten_command.strip().lower() != original_command.strip().lower():
        parts.append(f'REWRITTEN COMMAND: {rewritten_command}')
    if clarifications:
        parts.append('CLARIFICATION:')
        for question, answer in clarifications:
            parts += [f'Q: {question}', f'A: {answer}']
    parts += ['BEHAVIOR TREE:', outline]
    return '\n'.join(parts)


# --- What the generator sees --------------------------------------------------

def parse_generator_reply(answer, extract_code):
    """Return ('code', code) or ('clarify', question).

    ``extract_code`` is BTGenerationStage.extract_code from generator.py. Code wins when
    the reply holds both; plain text without the CLARIFY: marker is still treated as a
    question, and the caller logs a format warning for it.
    """
    code = extract_code(answer)
    if code is not None:
        return 'code', code
    text = answer.strip()
    if text.upper().startswith('CLARIFY:'):
        return 'clarify', text[len('CLARIFY:'):].strip()
    return 'clarify', text


def generator_message(command, clarifications=(), previous_code=None, problems=None):
    """The user message for one generator call.

    ``problems`` is the text from syntax_problems() or reviewer_problems() and belongs to
    ``previous_code``; both are left out on the first call.
    """
    parts = [f'COMMAND: {command}']
    if clarifications:
        parts.append('CLARIFICATION:')
        for question, answer in clarifications:
            parts += [f'Q: {question}', f'A: {answer}']
    if previous_code:
        parts += ['PREVIOUS TREE:', previous_code, problems]
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
    problems = '; '.join(ERROR_CODES[code] for code in form['errors'])
    return f'REVIEWER FINDINGS:\nProblems: {problems}.\nReason: {form["reason"]}'


# --- The loop -----------------------------------------------------------------

CLARIFICATION_LIMIT = 2     # questions the generator may ask per run; one more ends the run
SYNTAX_FAILURE_LIMIT = 3    # the run ends at the 3rd tree that fails the syntax check
JUDGE_REJECTION_LIMIT = 3   # the run ends at the 3rd rejected tree (study design: max 3)
JUDGE_FORMAT_RETRIES = 2    # extra judge calls when a reply is not a valid form


def run_generation_loop(command, original_command, rewritten_command,
                        generate, syntax_check, judge, ask_user, extract_code,
                        clock=None):
    """Generator, clarification, syntax check and judge, until a tree is accepted.

    command            the text the generator works from (the rewritten command when
                       enrichment ran, otherwise the original)
    generate(message)          -> the generator's raw reply
    syntax_check(code)         -> (passed, built_tree_or_None, checks)
    judge(message)             -> the judge's raw reply
    ask_user(question)         -> the user's answer, or None when nobody answers
    extract_code               BTGenerationStage.extract_code

    Returns a record with the final status, every attempt, the counters and the times.
    """
    import time
    clock = clock or time.time
    record = {
        'status': None, 'attempts': [], 'clarifications': [], 'accepted_tree': None,
        'counts': {'generator_calls': 0, 'clarifications': 0, 'syntax_failures': 0,
                   'judge_calls': 0, 'judge_rejections': 0, 'judge_format_errors': 0},
        'times': {'loop_started': clock(), 'first_valid_tree': None, 'accepted': None},
    }
    counts = record['counts']

    def finish(status):
        record['status'] = status
        return record

    previous_code = problems = None
    while True:
        message = generator_message(command, record['clarifications'], previous_code, problems)
        reply = generate(message)
        counts['generator_calls'] += 1
        kind, body = parse_generator_reply(reply, extract_code)
        attempt = {'n': counts['generator_calls'], 'generator_message': message,
                   'generator_reply': reply, 'kind': kind}
        record['attempts'].append(attempt)

        # The generator asked a question instead of writing code.
        if kind == 'clarify':
            counts['clarifications'] += 1
            attempt['question'] = body
            attempt['format_warning'] = not reply.strip().upper().startswith('CLARIFY:')
            if counts['clarifications'] > CLARIFICATION_LIMIT:
                return finish('failed_clarification_cap')
            answer = ask_user(body)
            if answer is None:
                return finish('no_answer')
            attempt['answer'] = answer
            record['clarifications'].append((body, answer))
            continue    # the previous tree and its problems, if any, are sent again

        # Syntax check.
        attempt['code'] = body
        passed, tree, checks = syntax_check(body)
        attempt['syntax_passed'] = passed
        if not passed:
            counts['syntax_failures'] += 1
            previous_code, problems = body, syntax_problems(checks)
            attempt['syntax_errors'] = problems
            if counts['syntax_failures'] >= SYNTAX_FAILURE_LIMIT:
                return finish('failed_syntax_cap')
            continue
        if record['times']['first_valid_tree'] is None:
            record['times']['first_valid_tree'] = clock()

        # Semantic judge. A fresh call for every tree: it does not see earlier verdicts.
        outline = outline_for_judge(tree)
        judge_input = judge_message(original_command, rewritten_command,
                                    record['clarifications'], outline)
        attempt.update({'outline': outline, 'judge_message': judge_input,
                        'judge_replies': [], 'judge_form': None})
        message_to_judge = judge_input
        for _ in range(1 + JUDGE_FORMAT_RETRIES):
            counts['judge_calls'] += 1
            raw = judge(message_to_judge)
            attempt['judge_replies'].append(raw)
            try:
                attempt['judge_form'] = parse_judgement(raw)
                break
            except ValueError as error:
                counts['judge_format_errors'] += 1
                message_to_judge = (f'{judge_input}\n\nYour previous answer was not a valid '
                                    f'judgement form: {error}. Answer with only the JSON object.')
        form = attempt['judge_form']
        if form is None:
            return finish('judge_error')
        if form['verdict'] == 'accept':
            record['accepted_tree'] = tree
            record['times']['accepted'] = clock()
            return finish('accepted')

        counts['judge_rejections'] += 1
        if counts['judge_rejections'] >= JUDGE_REJECTION_LIMIT:
            return finish('failed_judge_cap')
        previous_code, problems = body, reviewer_problems(form)
