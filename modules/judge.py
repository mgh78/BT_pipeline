"""The semantic judge: does this tree do what the user asked, in a way the robot can?

It runs after every tree that passes the syntax check. It fills in the judgement form -
accept or reject, which categories are wrong, and one sentence saying why - and on a
rejection that form goes back to the generator as the feedback for the next tree.

What it deliberately does not get: the Python code, the scene's target state, the
verdicts it gave earlier in the run, and the photo unless the generator gets it too.
Every tree is judged on its own, from the command the user actually typed.

It never writes or repairs a tree, and a judge that fails is never treated as an accept.
"""

import config
from core import logging_setup
from core.pipeline import StageError
from modules import llm, loop

log = logging_setup.get_logger('judge')


class SemanticJudge:
    """One judge, reused for every call in a run."""

    name = 'judge'
    title = 'Semantic judge'

    def __init__(self, model=None, temperature=None, use_structured_output=None,
                 reasoning_effort=None):
        self.model = model or config.JUDGE_MODEL
        self.reasoning_effort = reasoning_effort or config.JUDGE_REASONING_EFFORT
        self.temperature = (config.JUDGE_TEMPERATURE if temperature is None
                            else temperature)
        self.structured = (config.JUDGE_USE_STRUCTURED_OUTPUT
                           if use_structured_output is None else use_structured_output)
        self.log = log

    def system_prompt(self, scene):
        """The judge prompt with this scene's object list inserted.

        Filled with ``str.replace``: the prompt contains the literal braces of the
        judgement form, so ``str.format`` would break it.
        """
        path = config.SEMANTIC_JUDGE_PROMPT_FILE
        if not path.exists():
            raise StageError(f'The judge prompt is missing: {path}')
        prompt = path.read_text(encoding='utf-8')
        if '{scene_objects}' not in prompt:
            self.log.warning('%s has no {scene_objects} placeholder — the judge will '
                             'not be told which objects are in the scene', path.name)
        return prompt.replace('{scene_objects}', scene.objects_block())

    def ask(self, message, scene, context=None, tag='judge'):
        """Send one judge call and return its raw reply.

        The reply is validated by the caller with ``loop.parse_judgement``, which runs
        even with structured output: a schema can enforce the shape of the form, but
        not that an accepted tree lists no errors.
        """
        image = scene.image_path if config.JUDGE_SEND_SCENE_IMAGE else None
        reply = llm.ask(
            system_prompt=self.system_prompt(scene),
            text=message,
            model=self.model,
            temperature=self.temperature,
            logger=self.log,
            context=context,
            image_path=image,
            tag=tag,
            response_format=loop.RESPONSE_FORMAT if self.structured else None,
            reasoning_effort=self.reasoning_effort)
        return reply['text']

    def describe(self):
        """What is recorded about this judge in the run's summary."""
        return {'model': self.model, 'temperature': self.temperature,
                'reasoning_effort': llm.reasoning_effort_for(
                    self.model, self.reasoning_effort),
                'structured_output': self.structured,
                'scene_image': config.JUDGE_SEND_SCENE_IMAGE}


def form_summary(form):
    """One readable line for a judgement form, for the log and the window."""
    if form is None:
        return 'no valid form'
    if form['verdict'] == 'accept':
        return 'accepted'
    return f'rejected — {"; ".join(loop.form_sentences(form))}. {form["reason"]}'
