"""Stage 3 - enrich the command with the scene context.

This is the contextual-asr post-processing step, unchanged: the same five prompt files
are assembled in the same order, the scene knowledge dictionary is inserted into
``scene_knowledge.txt``, and the scene photo is attached to the user message. The
model rewrites a vague command into a precise one that names the objects actually on
the table.

The prompt files are read from the contextual-asr project rather than copied, so there
is only ever one version of them.
"""

import re

import config
from core.pipeline import Stage, StageError, StageStatus
from modules import llm

# Assembled in this order, exactly as contextual-asr's PostProcessor does it.
PROMPT_PARTS = ('context_abstract', 'task_description', 'robot_functions')

# The rules file requires "a concise, direct imperative command". When the model
# answers with a refusal instead, that refusal must not be passed on as if it were the
# command - the generator would then be asked to build a tree for an apology.
REFUSAL_PATTERN = re.compile(
    r"^\s*(i'm sorry|i am sorry|sorry[,.]|i cannot|i can't|i can not|i'm unable|"
    r"i am unable|i'm not able|as an ai|unfortunately[,.])", re.IGNORECASE)

# The contextual-asr prompt files promise the model a photo of the scene. When the
# photo is not sent, those promises have to go, or the model is told to look at an
# image that is not there. The files themselves are left untouched - they are shared
# with contextual-asr - so the edits are made on the assembled text instead.
IMAGE_SENTENCES = (
    ('Based on the provided image of the initial state of the scene and the '
     'transcribed user command,',
     'Based on the list of objects in the scene below and the transcribed user '
     'command,'),
    (' An image of the scene is also included in the prompt for reference.', ''),
    ('You should be able to map the objects in the image to their corresponding '
     'names and attributes from this list.\n', ''),
)


def without_image_references(prompt):
    """Remove the sentences that tell the model to look at a scene photo."""
    for sentence, replacement in IMAGE_SENTENCES:
        prompt = prompt.replace(sentence, replacement)
    return prompt


class EnrichmentStage(Stage):
    """Rewrite the command so that it refers to the objects in this scene."""

    name = 'enrichment'
    title = 'Scene-aware command'
    description = 'Rewrite the command using the names of the objects in the scene.'

    def build_system_prompt(self, scene):
        """Concatenate the enrichment prompt files and fill in the scene knowledge."""
        directory = config.ENRICHMENT_PROMPT_DIR
        missing = [part for part in (*PROMPT_PARTS, 'scene_knowledge', 'rules')
                   if not (directory / f'{part}.txt').exists()]
        if missing:
            raise StageError(f'Missing enrichment prompt files in {directory}: '
                             f'{", ".join(missing)}')

        prompt = ''.join((directory / f'{part}.txt').read_text(encoding='utf-8')
                         for part in PROMPT_PARTS)
        scene_knowledge = (directory / 'scene_knowledge.txt').read_text(encoding='utf-8')
        prompt += scene_knowledge.replace('{scene_knowledge_dictionary}',
                                          scene.normalized_json())
        prompt += (directory / 'rules.txt').read_text(encoding='utf-8')
        if not config.ENRICHMENT_SEND_SCENE_IMAGE:
            prompt = without_image_references(prompt)
        return prompt

    def execute(self, context, payload):
        scene = payload.get('scene_object')
        command = (payload.get('command') or '').strip()
        if scene is None:
            raise StageError('Run the scene stage first.')
        if not command:
            raise StageError('There is no command to enrich.')

        system_prompt = self.build_system_prompt(scene)
        image = scene.image_path if config.ENRICHMENT_SEND_SCENE_IMAGE else None
        model = payload.get('enrichment_model') or config.ENRICHMENT_MODEL
        payload['enrichment_on'] = True
        payload['enrichment'] = {'model': model,
                                 'temperature': config.ENRICHMENT_TEMPERATURE,
                                 'scene_image': config.ENRICHMENT_SEND_SCENE_IMAGE}

        reply = llm.ask(
            system_prompt=system_prompt,
            text=command,
            model=model,
            temperature=config.ENRICHMENT_TEMPERATURE,
            logger=self.log,
            context=context,
            image_path=image,
            tag='enrichment')

        enriched = reply['text'].strip().strip('"')
        if not enriched:
            raise StageError('The model returned an empty command.')
        if REFUSAL_PATTERN.match(enriched):
            # Stop here rather than handing a refusal to the generator as the command.
            self.log.error('the model refused to rewrite the command: %s', enriched)
            raise StageError(
                f'The model refused to rewrite the command instead of returning one '
                f'("{enriched[:80]}"). Rephrase the command, or turn off "Enrich with '
                f'the scene first" to send it to the generator as typed.')

        payload['enriched_command'] = enriched
        self.log.info('enriched: %s', enriched)

        changed = enriched.lower() != command.lower()
        if not changed:
            self.log.info('the command was already scene-specific; it is unchanged')

        artifacts = dict(reply['artifacts'])
        artifacts['enriched command'] = context.write_text('enriched_command.txt', enriched)

        return self.result(
            StageStatus.PASSED,
            summary=(f'rewritten in {reply["seconds"]:.1f}s' if changed
                     else f'unchanged after {reply["seconds"]:.1f}s'),
            detail={
                'original': command,
                'enriched': enriched,
                'changed': changed,
                'model': reply['model'],
                'seconds': round(reply['seconds'], 2),
                **reply['usage'],
            },
            artifacts=artifacts)
