"""The BT creator: turns one command into a behavior tree.

It does one thing only. It translates the command into the four actions, in the order
the user gave them, and it always returns a tree - an unclear command is read the most
reasonable way rather than questioned, and a part no action can carry out is left out.
It does not check whether the plan is safe, complete or well ordered: the semantic
judge does that, and sends its findings back here for the next attempt.

So a tree that shakes an open test tube because the user never mentioned a cap is
intended behaviour now, not a bug.
"""

import config
from core import logging_setup
from modules import llm, xml_tree
from modules.prompt_files import load_prompt

log = logging_setup.get_logger('generator')


class BTGenerator:
    """One generator, reused for every call in a run."""

    name = 'generator'
    title = 'Behavior tree'

    def __init__(self, model=None, temperature=None, reasoning_effort=None):
        self.model = model or config.BT_GENERATION_MODEL
        self.reasoning_effort = reasoning_effort or config.BT_GENERATION_REASONING_EFFORT
        self.temperature = (config.BT_GENERATION_TEMPERATURE if temperature is None
                            else temperature)
        self.log = log

    def system_prompt(self, scene):
        """The generation prompt, with this scene's object list where it has the placeholder.

        The generic prompt has none: the generator is not told what is on the table.

        Filled with ``str.replace``: the prompt contains literal ``{key}`` references,
        so ``str.format`` would break it.
        """
        path = config.BT_GENERATION_PROMPT_FILE
        prompt = load_prompt(path)
        return prompt.replace('{scene_objects}', scene.objects_block())

    @staticmethod
    def extract_code(answer):
        """Return the XML tree in the reply, or None when the reply holds no tree.

        Keeps its old name, so the loop and its tests need no change; the generator now
        writes XML, read by ``xml_tree.extract_xml``.
        """
        return xml_tree.extract_xml(answer)

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
            tag=tag,
            reasoning_effort=self.reasoning_effort)
        return reply['text']

    def describe(self):
        """What is recorded about this generator in the run's summary."""
        return {'model': self.model,
                'temperature': llm.temperature_for(self.model, self.temperature),
                'reasoning_effort': llm.reasoning_effort_for(
                    self.model, self.reasoning_effort),
                'scene_image': config.BT_GENERATION_SEND_SCENE_IMAGE}


def as_document(tree_xml, payload):
    """An accepted XML tree with a comment saying where it came from, for the record.

    The file is a complete XML document that ``py_trees.parsers.behaviour_tree_xml``
    reads as it is, with the node classes of ``modules/bt_nodes.py`` registered.
    """
    def safe(text):         # "--" may not appear inside an XML comment
        return str(text or '-').replace('--', '- -')

    header = ('<!--\n'
              f'  Scene:    {safe(payload.get("scene"))}\n'
              f'  Command:  {safe(payload.get("command"))}\n'
              f'  Enriched: {safe(payload.get("enriched_command"))}\n'
              f'  Model:    {safe(payload.get("generation_model") or config.BT_GENERATION_MODEL)}\n'
              '-->\n')
    return header + tree_xml + '\n'
