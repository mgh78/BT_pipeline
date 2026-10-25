"""A reasoning model is called through the Responses API; every other model is not.

The API client is replaced by a fake, so nothing here calls the network.

    ../contextual-asr/venv/bin/python -m pytest tests -q
"""

import logging
import os
import sys
import types

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import config  # noqa: E402
from modules import llm, loop  # noqa: E402

LOG = logging.getLogger('test')


class FakeClient:
    """Records the arguments of the call; ``refuse_temperature`` makes the first fail."""

    instances = []
    refuse_temperature = False

    def __init__(self, api_key=None):
        self.calls = []
        self.responses = types.SimpleNamespace(create=self.create_response)
        self.chat = types.SimpleNamespace(
            completions=types.SimpleNamespace(create=self.create_chat))
        FakeClient.instances.append(self)

    def create_response(self, **arguments):
        self.calls.append(('responses', arguments))
        if FakeClient.refuse_temperature and 'temperature' in arguments:
            raise ValueError("Unsupported parameter: 'temperature' is not supported")
        usage = types.SimpleNamespace(input_tokens=11, output_tokens=5, total_tokens=16)
        return types.SimpleNamespace(output_text=' tree ', usage=usage)

    def create_chat(self, **arguments):
        self.calls.append(('chat', arguments))
        usage = types.SimpleNamespace(prompt_tokens=7, completion_tokens=3, total_tokens=10)
        message = types.SimpleNamespace(content=' tree ')
        return types.SimpleNamespace(choices=[types.SimpleNamespace(message=message)],
                                     usage=usage)


@pytest.fixture
def client(monkeypatch):
    FakeClient.instances = []
    FakeClient.refuse_temperature = False
    monkeypatch.setitem(sys.modules, 'openai', types.SimpleNamespace(OpenAI=FakeClient))
    monkeypatch.setattr(llm, 'load_api_key', lambda: 'key')
    return FakeClient


def ask(model, **extra):
    return llm.ask('SYSTEM', 'COMMAND', model, 0, LOG, tag='t', **extra)


def test_luna_goes_through_the_responses_api_with_its_effort(client):
    reply = ask('gpt-6-luna', reasoning_effort='high')
    api, arguments = client.instances[0].calls[0]
    assert api == 'responses'
    assert arguments['reasoning'] == {'effort': 'high'}
    assert arguments['instructions'] == 'SYSTEM'
    assert arguments['input'] == [{'role': 'user', 'content': [
        {'type': 'input_text', 'text': 'COMMAND'}]}]
    assert reply['text'] == 'tree'
    assert reply['usage'] == {'prompt_tokens': 11, 'completion_tokens': 5,
                              'total_tokens': 16}


def test_the_judge_form_is_requested_in_the_responses_format(client):
    ask('gpt-6-luna', reasoning_effort='medium', response_format=loop.RESPONSE_FORMAT)
    text_format = client.instances[0].calls[0][1]['text']['format']
    assert text_format['type'] == 'json_schema'
    assert text_format['name'] == 'judgement_form'
    assert text_format['strict'] is True
    assert text_format['schema'] == loop.JUDGE_SCHEMA


def test_other_models_keep_chat_completions_and_get_no_effort(client):
    ask('gpt-4o', reasoning_effort='high')
    api, arguments = client.instances[0].calls[0]
    assert api == 'chat'
    assert 'reasoning' not in arguments and 'reasoning_effort' not in arguments


def test_luna_is_sent_no_temperature_so_nothing_is_retried(client):
    client.refuse_temperature = True
    ask('gpt-6-luna', reasoning_effort='medium')
    calls = client.instances[0].calls
    assert len(calls) == 1 and 'temperature' not in calls[0][1]


def test_other_models_still_get_their_temperature(client):
    ask('gpt-4o')
    assert client.instances[0].calls[0][1]['temperature'] == 0


def test_the_effort_is_recorded_only_for_a_model_that_uses_it():
    assert llm.reasoning_effort_for('gpt-6-luna', 'medium') == 'medium'
    assert llm.reasoning_effort_for('gpt-4o', 'medium') is None
    assert llm.temperature_for('gpt-6-luna', 0) is None
    assert llm.temperature_for('gpt-4o', 0) == 0
    assert 'gpt-6-luna' in config.AVAILABLE_MODELS


def test_the_effort_chosen_for_a_run_reaches_the_model_call(client):
    from modules.generator import BTGenerator
    from modules.judge import SemanticJudge

    scene = types.SimpleNamespace(objects_block=lambda: '- a: cube', image_path=None)
    BTGenerator(model='gpt-6-luna', reasoning_effort='low').ask('go', scene)
    SemanticJudge(model='gpt-6-luna', reasoning_effort='high').ask('go', scene)
    efforts = [instance.calls[0][1]['reasoning']['effort']
               for instance in client.instances]
    assert efforts == ['low', 'high']
    assert BTGenerator(model='gpt-6-luna').describe()['reasoning_effort'] == 'medium'
    assert BTGenerator(model='gpt-6-luna').describe()['temperature'] is None
    assert BTGenerator(model='gpt-4o', reasoning_effort='low').describe()[
        'reasoning_effort'] is None
