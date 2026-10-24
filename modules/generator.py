"""The BT creator: turns one command into a behavior tree.

It does one thing only. It translates the command into the four actions, in the order
the user gave them, and it always returns a tree - an unclear command is read the most
reasonable way rather than questioned, and a part no action can carry out is left out.
It does not check whether the plan is safe, complete or well ordered: the semantic
judge does that, and sends its findings back here for the next attempt.

So a tree that shakes an open test tube because the user never mentioned a cap is
intended behaviour now, not a bug.
"""

import re

import config
from core import logging_setup
from modules import llm
from modules.prompt_files import load_prompt

log = logging_setup.get_logger('generator')

CODE_BLOCK_PATTERN = re.compile(r'```(?:python)?\s*(.*?)```', re.DOTALL)


class BTGenerator:
    """One generator, reused for every call in a run."""

    name = 'generator'
    title = 'Behavior tree'

    def __init__(self, model=None, temperature=None):
        self.model = model or config.BT_GENERATION_MODEL
        self.temperature = (config.BT_GENERATION_TEMPERATURE if temperature is None
                            else temperature)
        self.log = log

    def system_prompt(self, scene):
        """The generation prompt with this scene's object list inserted.

        The prompt is assembled from the parts in ``prompts/generation`` that
        ``bt_generation_prompt.txt`` includes. Filled with ``str.replace``: the prompt contains the literal ``{e}`` of the
        except block, so ``str.format`` would break it.
        """
        path = config.BT_GENERATION_PROMPT_FILE
        prompt = load_prompt(path)
        if '{scene_objects}' not in prompt:
            self.log.warning('%s has no {scene_objects} placeholder — the model will '
                             'not be told which objects are in the scene', path.name)
        return prompt.replace('{scene_objects}', scene.objects_block())

    @staticmethod
    def extract_code(answer):
        """Return the code in the reply, or None when the reply is not code.

        None means the generator asked a question instead; the loop reads that with
        ``loop.parse_generator_reply``.
        """
        match = CODE_BLOCK_PATTERN.search(answer)
        if match:
            return match.group(1).strip()
        # A model that forgets the fence but still returns the function.
        if 'def create_behavior_tree' in answer:
            return answer.strip()
        return None

    def ask(self, message, scene, context=None, tag='generation'):
        """Send one generator call and return its raw reply."""
        image = scene.image_path if config.BT_GENERATION_SEND_SCENE_IMAGE else None
        reply = llm.ask(
            system_prompt=self.system_prompt(scene),
            text=message,
            model=self.model,
            temperature=self.temperature,
            logger=self.log,
            context=context,
            image_path=image,
            tag=tag)
        return reply['text']

    def describe(self):
        """What is recorded about this generator in the run's summary."""
        return {'model': self.model, 'temperature': self.temperature,
                'scene_image': config.BT_GENERATION_SEND_SCENE_IMAGE}


def as_module(code, payload):
    """Wrap a generated function in a runnable module, for the record.

    The imports name the action nodes the simulator will provide later; nothing in the
    pipeline imports this file, it is saved so an accepted tree can be read and run on
    its own once the executor exists.
    """
    header = (
        f'# Scene:    {payload.get("scene")}\n'
        f'# Command:  {payload.get("command")}\n'
        f'# Enriched: {payload.get("enriched_command") or "-"}\n'
        f'# Model:    {payload.get("generation_model") or config.BT_GENERATION_MODEL}\n\n'
        'import logging\n\n'
        'import py_trees\n\n'
        '# The action nodes are provided by the simulator side of the pipeline.\n'
        'from bt_nodes import Place, Pour, Shake, Close\n\n\n')
    return header + code + '\n'
