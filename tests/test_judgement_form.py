"""The judgement form carries free-text errors, with no fixed categories.

    ../contextual-asr/venv/bin/python -m pytest tests -q
"""

import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from modules import loop  # noqa: E402


def form(verdict, errors, reason):
    import json
    return json.dumps({'verdict': verdict, 'errors': errors, 'reason': reason})


def test_any_wording_is_accepted_as_an_error():
    parsed = loop.parse_judgement(form('reject', ['  wrong cube  ', 'no cap'], 'x'))
    assert parsed['errors'] == ['wrong cube', 'no cap']
    assert loop.form_sentences(parsed) == ['wrong cube', 'no cap']


def test_repeated_errors_are_listed_once():
    parsed = loop.parse_judgement(form('reject', ['no cap', 'no cap'], 'x'))
    assert parsed['errors'] == ['no cap']


@pytest.mark.parametrize('errors', [[''], ['  '], [3], 'no cap'])
def test_empty_or_non_text_errors_are_refused(errors):
    with pytest.raises(ValueError):
        loop.parse_judgement(form('reject', errors, 'x'))


def test_a_rejection_still_needs_an_error_and_a_reason():
    with pytest.raises(ValueError):
        loop.parse_judgement(form('reject', [], 'x'))
    with pytest.raises(ValueError):
        loop.parse_judgement(form('reject', ['no cap'], ' '))


def test_an_accept_cannot_carry_errors():
    with pytest.raises(ValueError):
        loop.parse_judgement(form('accept', ['no cap'], ''))
