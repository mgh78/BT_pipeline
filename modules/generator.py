"""Stage 4 - generate the behavior tree with ChatGPT.

The system prompt is ``prompts/bt_generation_prompt.txt`` with ``{scene_objects}``
filled in from the loaded scene, and the scene photo is attached so the model can
resolve references such as "the left test tube".

The model answers in one of two ways, and the prompt makes it choose:

* a ``python`` code block holding ``create_behavior_tree()`` - the command was accepted;
* plain text - the command was declined under Rule U (something is missing or
  ambiguous) or Rule A (the robot cannot do what was asked).

A declined command is not a failure of this stage: it is the generator working as
specified, so the stage reports ``REJECTED`` and the run stops with the model's own
explanation shown to the user.
"""

import re

import config
from core.pipeline import Stage, StageError, StageStatus
from modules import llm

CODE_BLOCK_PATTERN = re.compile(r'```(?:python)?\s*(.*?)```', re.DOTALL)


class BTGenerationStage(Stage):
    """Ask the model for ``create_behavior_tree()`` and keep what it answered."""

    name = 'generator'
    title = 'Behavior tree'
    description = 'Ask ChatGPT for the create_behavior_tree() function.'

    def build_system_prompt(self, scene):
        """Return the generation prompt with this scene's object list inserted."""
        path = config.BT_GENERATION_PROMPT_FILE
        if not path.exists():
            raise StageError(f'The generation prompt is missing: {path}')
        prompt = path.read_text(encoding='utf-8')
        if '{scene_objects}' not in prompt:
            self.log.warning('%s has no {scene_objects} placeholder — the model will '
                             'not be told which objects are in the scene', path.name)
        return prompt.replace('{scene_objects}', scene.objects_block())

    @staticmethod
    def extract_code(answer):
        """Return the code in the reply, or None when the reply is plain text."""
        match = CODE_BLOCK_PATTERN.search(answer)
        if match:
            return match.group(1).strip()
        # A model that forgets the fence but still returns the function.
        if 'def create_behavior_tree' in answer:
            return answer.strip()
        return None

    def execute(self, context, payload):
        scene = payload.get('scene_object')
        if scene is None:
            raise StageError('Run the scene stage first.')

        # The enriched command is what the generator should see; fall back to the raw
        # one when enrichment was skipped.
        command = (payload.get('enriched_command') or payload.get('command') or '').strip()
        if not command:
            raise StageError('There is no command to generate a tree from.')
        payload['generator_input'] = command

        system_prompt = self.build_system_prompt(scene)
        image = scene.image_path if config.BT_GENERATION_SEND_SCENE_IMAGE else None

        reply = llm.ask(
            system_prompt=system_prompt,
            text=command,
            model=payload.get('generation_model') or config.BT_GENERATION_MODEL,
            temperature=config.BT_GENERATION_TEMPERATURE,
            logger=self.log,
            context=context,
            image_path=image,
            tag='generation')

        answer = reply['text']
        code = self.extract_code(answer)
        payload['answer'] = answer
        payload['code'] = code

        artifacts = dict(reply['artifacts'])
        detail = {
            'command sent': command,
            'model': reply['model'],
            'seconds': round(reply['seconds'], 2),
            **reply['usage'],
        }

        # The model declined the command, as Rule U or Rule A tells it to.
        if code is None:
            self.log.warning('the generator declined the command: %s', answer)
            artifacts['explanation'] = context.write_text('rejection.txt', answer)
            return self.result(
                StageStatus.REJECTED,
                summary='the generator declined the command',
                detail={**detail, 'explanation': answer},
                artifacts=artifacts)

        artifacts['behavior tree'] = context.write_text('bt.py', self._as_module(code, payload))
        artifacts['function only'] = context.write_text('create_behavior_tree.py', code + '\n')

        lines = code.count('\n') + 1
        self.log.info('generated %d lines of behavior tree code', lines)
        self.log.debug('generated code:\n%s', code)

        return self.result(
            StageStatus.PASSED,
            summary=f'{lines} lines generated in {reply["seconds"]:.1f}s',
            detail={**detail, 'lines': lines},
            artifacts=artifacts)

    @staticmethod
    def _as_module(code, payload):
        """Wrap the generated function in a runnable module, for the record.

        The imports name the action nodes the simulator will provide later; nothing in
        this phase of the pipeline imports this file, it is saved so the generated tree
        can be read and run on its own once the executor exists.
        """
        header = (
            f'# Scene:   {payload.get("scene")}\n'
            f'# Command: {payload.get("command")}\n'
            f'# Enriched: {payload.get("enriched_command") or "-"}\n'
            f'# Model:   {payload.get("generation_model") or config.BT_GENERATION_MODEL}\n\n'
            'import logging\n\n'
            'import py_trees\n\n'
            '# The action nodes are provided by the simulator side of the pipeline.\n'
            'from bt_nodes import Place, Pour, Shake, Close\n\n\n')
        return header + code + '\n'
