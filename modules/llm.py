"""The one place the pipeline talks to ChatGPT.

Every call is logged the same way and leaves the same artifacts behind - the exact
system prompt, the exact user text, the raw reply, the token counts and the latency -
so any answer the model gave can be reread later next to the prompt that produced it.
"""

import base64
import os
import re
import time

import config
from core import logging_setup
from core.pipeline import StageError

log = logging_setup.get_logger('generator')


def load_api_key():
    """Return the API key from the environment, or from config.API_KEY_FILE."""
    key = os.environ.get('OPENAI_API_KEY', '').strip()
    if key:
        return key
    if os.path.exists(config.API_KEY_FILE):
        key = open(config.API_KEY_FILE, 'r', encoding='utf-8').read().strip()
    if not key:
        raise StageError(
            f'No OpenAI API key. Put it in {config.API_KEY_FILE} (the file must contain '
            f'only the key) or set the OPENAI_API_KEY environment variable.')
    return key


def readable_error(error):
    """Turn an API error into one sentence a person can act on.

    The client raises with the whole JSON body attached, which is unreadable in a
    status line, so the common cases get their own wording and anything else is
    shortened to the message the service sent.
    """
    text = str(error)
    code = ''
    match = re.search(r"'code': '([^']+)'", text)
    if match:
        code = match.group(1)

    if code in ('credit_balance_exhausted', 'insufficient_quota'):
        return ('The OpenAI account has no credits left — add credits at '
                'platform.openai.com/settings/organization/billing, then run again.')
    if code == 'invalid_api_key' or 'Incorrect API key' in text:
        return (f'The API key was rejected. Check {config.API_KEY_FILE} holds only the '
                f'key, or set OPENAI_API_KEY.')
    if code == 'model_not_found' or 'does not exist' in text:
        return 'This account cannot use that model — choose another one and run again.'
    if code == 'rate_limit_exceeded':
        return 'The model is rate limiting this account — wait a moment and run again.'
    if 'Connection' in type(error).__name__ or 'Timeout' in type(error).__name__:
        return f'Could not reach the API ({type(error).__name__}). Check the connection.'

    message = re.search(r"'message': '([^']+)'", text)
    return f'The model call failed: {message.group(1) if message else text}'


def encode_image(path):
    """Return a base64 data url for a scene photo, or None when there is no photo."""
    if not path or not os.path.exists(path):
        return None
    with open(path, 'rb') as f:
        return 'data:image/jpeg;base64,' + base64.b64encode(f.read()).decode('utf-8')


def ask(system_prompt, text, model, temperature, logger, context=None,
        image_path=None, tag='llm'):
    """Send one chat completion and return ``{'text', 'usage', 'seconds', 'model'}``.

    Args:
        system_prompt: the developer message, the whole instruction set.
        text: the user message - the command.
        model, temperature: which model to ask and how deterministic to be.
        logger: the calling module's logger, so the call appears in its own log file.
        context: the RunContext, when the prompt and reply should be saved as artifacts.
        image_path: a scene photo to attach to the user message.
        tag: artifact name prefix, for example 'enrichment' or 'generation'.

    Returns:
        dict with the reply text, token usage, elapsed seconds and the model used, plus
        an ``artifacts`` mapping of what was written to disk.
    """
    from openai import OpenAI  # Imported lazily so the GUI starts without the package.

    user_content = []
    image_url = encode_image(image_path)
    if image_url:
        user_content.append({'type': 'image_url',
                             'image_url': {'url': image_url, 'detail': 'high'}})
    user_content.append({'type': 'text', 'text': str(text)})

    artifacts = {}
    if context is not None:
        artifacts[f'{tag} prompt'] = context.write_text(
            f'{tag}/system_prompt.txt', system_prompt)
        artifacts[f'{tag} input'] = context.write_text(f'{tag}/user_message.txt', text)

    logging_setup.event(
        logger, 'llm.request', f'asking {model} ({len(system_prompt)} chars of prompt'
                               f'{", photo attached" if image_url else ""})',
        model=model, temperature=temperature, prompt_chars=len(system_prompt),
        image=bool(image_url), user_text=str(text))

    client = OpenAI(api_key=load_api_key())
    started = time.time()
    try:
        response = client.chat.completions.create(
            model=model,
            temperature=temperature,
            messages=[
                {'role': 'developer', 'content': system_prompt},
                {'role': 'user', 'content': user_content},
            ])
    except Exception as error:  # noqa: BLE001 - turn any client error into a stage error
        logger.error('the model call failed: %s', error)
        raise StageError(readable_error(error)) from error

    seconds = time.time() - started
    answer = (response.choices[0].message.content or '').strip()
    usage = {}
    if getattr(response, 'usage', None):
        usage = {
            'prompt_tokens': response.usage.prompt_tokens,
            'completion_tokens': response.usage.completion_tokens,
            'total_tokens': response.usage.total_tokens,
        }

    if context is not None:
        artifacts[f'{tag} reply'] = context.write_text(f'{tag}/raw_reply.txt', answer)

    logging_setup.event(
        logger, 'llm.response',
        f'{model} replied in {seconds:.2f}s ({usage.get("total_tokens", "?")} tokens)',
        model=model, seconds=round(seconds, 3), **usage)
    logger.debug('raw reply:\n%s', answer)

    return {'text': answer, 'usage': usage, 'seconds': seconds,
            'model': model, 'artifacts': artifacts}
