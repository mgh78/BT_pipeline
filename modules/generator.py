"""The BT creator: turns one command into a behavior tree.

It always returns a tree - an unclear command is read the most reasonable way rather
than questioned. What it is told comes from the mode (modules/modes.py), which picks
its prompt file:

- the Static creator (with or without the judge) gets only the command and translates
  it faithfully. It does not check whether the plan is physically possible: with a judge
  the judge does that and sends its findings back here; without one nothing does, so a
  tree that shakes an open test tube because the user never mentioned a cap is intended
  behaviour, not a bug.
- the Dynamic creator also gets the scene object list and the physical facts, and is
  asked to make the tree physically possible itself, since nothing checks it after.
"""

import config
from core import logging_setup
from core.pipeline import StageError
from modules import llm, modes, xml_tree
from modules.prompt_files import load_prompt

log = logging_setup.get_logger('generator')


class BTGenerator:
    """One generator, reused for every call in a run."""

    name = 'generator'
    title = 'Behavior tree'

    def __init__(self, mode, model=None, temperature=None, reasoning_effort=None):
        self.mode = mode
        self.model = model or config.BT_GENERATION_MODEL
        self.reasoning_effort = reasoning_effort or config.BT_GENERATION_REASONING_EFFORT
        self.temperature = (config.BT_GENERATION_TEMPERATURE if temperature is None
                            else temperature)
        self.log = log

    def system_prompt(self, scene):
        """The mode's creator prompt, with this scene's object list in its placeholder.

        Only the Dynamic creator's prompt has a ``{scene_objects}`` placeholder. The
        placeholder is checked against the mode, so a run can never quietly give a
        Static creator the scene, or a Dynamic creator none.

        Filled with ``str.replace``: the prompt contains literal ``{key}`` references,
        so ``str.format`` would break it.
        """
        path = self.mode.creator_prompt
        prompt = load_prompt(path)
        has_scene = '{scene_objects}' in prompt
        if self.mode.creator_sees_scene and not has_scene:
            raise StageError(f'{modes.relative(path)} has no {{scene_objects}} placeholder, '
                             f'but the {self.mode.title} mode shows the creator the scene.')
        if not self.mode.creator_sees_scene and has_scene:
            raise StageError(f'{modes.relative(path)} has a {{scene_objects}} placeholder, '
                             f'but the {self.mode.title} mode does not show the creator '
                             f'the scene.')
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
                'prompt': modes.relative(self.mode.creator_prompt),
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
              f'  Mode:     {safe(payload.get("mode_title"))}\n'
              f'  Command:  {safe(payload.get("command"))}\n'
              f'  Model:    {safe(payload.get("generation_model") or config.BT_GENERATION_MODEL)}\n'
              '-->\n')
    return header + tree_xml + '\n'
