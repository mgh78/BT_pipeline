"""Stage 1 - the scene.

Loads one of the nine scenes from the contextual-asr workspace knowledge and turns it
into the two forms the rest of the pipeline needs:

* ``objects_block()`` - the exact ``{scene_objects}`` text the behavior tree generator
  is given, one line per object with a unique id.
* ``normalized_json()`` - the scene dictionary with normalized object and color names,
  which is what the enrichment prompt is given.

The object ids produced here are the same ids the generator is told to use, so the
syntax tester can check a generated tree against this list and be sure they agree.
"""

import csv
import json
import re
from dataclasses import dataclass, field
from pathlib import Path

import config
from core.pipeline import Stage, StageError, StageStatus


def _words(text):
    """Split a CamelCase scene label into words: 'DarkGreen' -> 'dark green'."""
    return re.sub(r'(?<=[a-z0-9])(?=[A-Z])', ' ', text).replace('_', ' ').lower().strip()


def _snake(text):
    return re.sub(r'[^a-z0-9]+', '_', text.lower()).strip('_')


def _read_mapping(path, key, value):
    with open(path, newline='', encoding='utf-8') as f:
        return {row[key]: row[value] for row in csv.DictReader(f)}


def _normalization_maps():
    objects = _read_mapping(config.OBJECT_NORMALIZED_FILE,
                            'object name', 'normalized object name')
    colors = _read_mapping(config.COLOR_NORMALIZED_FILE,
                           'color name', 'normalized color name')
    return objects, colors


def find_scene_file(scene_number, ext='.json'):
    """Return the workspace knowledge file of a scene, or None when there is none."""
    for path in sorted(Path(config.WORKSPACE_KNOWLEDGE_DIR).rglob(f'*{ext}')):
        if scene_number in path.stem:
            return path
    return None


def find_scene_image(scene_number):
    return find_scene_file(scene_number, ext='.jpg')


@dataclass
class SceneObject:
    """One object on the table, with the id the generated code must use."""

    id: str
    name: str
    color: str
    role: str                 # 'graspable' or 'valid location'
    liquid_color: str = ''
    fill_amount: float = 0.0
    position: dict = field(default_factory=dict)

    @property
    def is_location(self):
        return self.role == 'valid location'

    @property
    def holds_liquid(self):
        return bool(self.liquid_color) or self.fill_amount > 0

    @property
    def is_container(self):
        """True when something can be poured into this object."""
        return self.is_location or any(
            word in self.name for word in ('cylinder', 'test tube', 'bowl', 'bottle', 'cup'))

    @property
    def is_cap(self):
        return 'cap' in self.name or 'lid' in self.name

    def as_line(self):
        """Render this object the way the generation prompt expects to see it."""
        attributes = [self.name, self.color, self.role]
        if self.holds_liquid:
            attributes.insert(2, f'contains {self.liquid_color} liquid '
                                 f'({round(self.fill_amount * 100)}% full)')
        return (f'- {self.id}: {", ".join(attributes)}, '
                f'position x={self.position["x"]:.3f} y={self.position["y"]:.3f} '
                f'z={self.position["z"]:.3f}')


@dataclass
class Scene:
    """A loaded scene: its objects, its photo and its raw knowledge file."""

    number: str
    objects: list
    json_path: Path
    image_path: Path | None
    raw: dict

    def objects_block(self):
        return '\n'.join(obj.as_line() for obj in self.objects)

    @property
    def ids(self):
        return [obj.id for obj in self.objects]

    def by_id(self, object_id):
        for obj in self.objects:
            if obj.id == object_id:
                return obj
        return None

    def normalized_json(self):
        """The scene dictionary with normalized names, as the enrichment prompt wants."""
        object_names, color_names = _normalization_maps()
        scene = json.loads(json.dumps(self.raw))  # a copy we are free to rewrite
        for part in scene.get('parts_by_transformation', []):
            part['name'] = object_names.get(part['name'], part['name'])
            part['color'] = color_names.get(part['color'], part['color']).lower()
            liquid = part.setdefault('liquid', {})
            liquid['color'] = color_names.get(liquid.get('color', ''),
                                              liquid.get('color', '')).lower()
        return json.dumps(scene, indent=4)


def load_scene(scene_number):
    """Read a scene and give every object a unique, stable id.

    Objects are ordered by type, color and then position (left to right, near to far),
    and only ids that would collide get a numeric suffix - so a unique object keeps a
    clean id such as ``yellow_bowl`` while duplicates become ``red_cuboid_1``,
    ``red_cuboid_2``.
    """
    json_path = find_scene_file(scene_number)
    if json_path is None:
        raise StageError(f'No workspace knowledge file found for {scene_number} '
                         f'in {config.WORKSPACE_KNOWLEDGE_DIR}')

    with open(json_path, 'r', encoding='utf-8') as f:
        raw = json.load(f)
    object_names, color_names = _normalization_maps()

    parts = []
    for part in raw.get('parts_by_transformation', []):
        liquid = part.get('liquid', {})
        parts.append({
            'name': _words(object_names.get(part['name'], part['name'])),
            'color': _words(color_names.get(part['color'], part['color'])),
            'liquid_color': _words(color_names.get(liquid.get('color', ''),
                                                   liquid.get('color', ''))),
            'fill_amount': liquid.get('fill_amount', 0.0),
            'position': part['transformation']['position'],
        })

    # Only index ids that are actually duplicated.
    counts = {}
    for part in parts:
        base = _snake(f"{part['color']} {part['name']}")
        counts[base] = counts.get(base, 0) + 1

    def spatial_order(part):
        return (part['name'], part['color'],
                round(part['position']['y'], 3), round(part['position']['x'], 3))

    seen = {}
    objects = []
    for part in sorted(parts, key=spatial_order):
        base = _snake(f"{part['color']} {part['name']}")
        if counts[base] > 1:
            seen[base] = seen.get(base, 0) + 1
            object_id = f'{base}_{seen[base]}'
        else:
            object_id = base
        objects.append(SceneObject(
            id=object_id,
            name=part['name'],
            color=part['color'],
            role='valid location' if part['name'] in config.SUPPORT_OBJECTS else 'graspable',
            liquid_color=part['liquid_color'],
            fill_amount=part['fill_amount'],
            position=part['position'],
        ))

    return Scene(number=scene_number, objects=objects, json_path=json_path,
                 image_path=find_scene_image(scene_number), raw=raw)


class SceneStage(Stage):
    """Load the chosen scene and record exactly what the generator will be shown."""

    name = 'scene'
    title = 'Scene'
    description = 'Load the scene photo and the object list the generator sees.'

    def execute(self, context, payload):
        scene_number = payload.get('scene')
        if not scene_number:
            raise StageError('No scene selected.')

        scene = load_scene(scene_number)
        payload['scene_object'] = scene
        payload['scene_objects_block'] = scene.objects_block()

        artifacts = {
            'object list': context.write_text('scene_objects.txt', scene.objects_block()),
            'scene knowledge': context.write_text('scene_knowledge.json',
                                                  scene.normalized_json()),
        }
        if scene.image_path:
            artifacts['scene photo'] = context.copy_in(scene.image_path, 'scene.jpg')

        graspable = sum(1 for o in scene.objects if not o.is_location)
        locations = sum(1 for o in scene.objects if o.is_location)
        self.log.info('scene %s loaded: %d objects (%d graspable, %d locations)',
                      scene_number, len(scene.objects), graspable, locations)
        for obj in scene.objects:
            self.log.debug('  %s', obj.as_line())

        return self.result(
            StageStatus.PASSED,
            summary=f'{len(scene.objects)} objects — {graspable} graspable, {locations} locations',
            detail={
                'scene': scene_number,
                'objects': len(scene.objects),
                'graspable': graspable,
                'locations': locations,
                'knowledge file': str(scene.json_path),
                'photo': str(scene.image_path) if scene.image_path else 'none',
                'object list': scene.objects_block(),
            },
            artifacts=artifacts)
