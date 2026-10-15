"""Every path and setting the pipeline uses, in one place.

Paths are absolute and derived from this file's own location, so the pipeline can be
started from any working directory.
"""

from pathlib import Path

# --- Locations ---------------------------------------------------------------

PIPELINE_ROOT = Path(__file__).resolve().parent
PROJECT_ROOT = PIPELINE_ROOT.parent

# The contextual-asr project supplies the scene knowledge and the enrichment prompts.
# They are read from there rather than copied, so there is a single source of truth.
CONTEXTUAL_ASR_DIR = PROJECT_ROOT / 'contextual-asr' / 'contextual-asr'
WORKSPACE_KNOWLEDGE_DIR = CONTEXTUAL_ASR_DIR / 'prompt' / 'workspace_knowledge'
OBJECT_NORMALIZED_FILE = WORKSPACE_KNOWLEDGE_DIR / 'object_normalized.csv'
COLOR_NORMALIZED_FILE = WORKSPACE_KNOWLEDGE_DIR / 'color_normalized.csv'
ENRICHMENT_PROMPT_DIR = CONTEXTUAL_ASR_DIR / 'prompt'

# The behavior tree generation prompt is ours to edit, so it lives here.
BT_GENERATION_PROMPT_FILE = PIPELINE_ROOT / 'prompts' / 'bt_generation_prompt.txt'

# The API key file. The OPENAI_API_KEY environment variable takes precedence.
API_KEY_FILE = CONTEXTUAL_ASR_DIR / 'API_KEY.txt'

DATA_DIR = PIPELINE_ROOT / 'data'
RUNS_DIR = DATA_DIR / 'runs'
LOG_DIR = DATA_DIR / 'logs'

# --- Scenes ------------------------------------------------------------------

# Scene 2 exists in two variants, so there are nine selectable scenes.
SCENES = ['scene1', 'scene2_1', 'scene2_2', 'scene3', 'scene4',
          'scene5', 'scene6', 'scene7', 'scene8']

# Normalized object names that hold or support other objects. These are never
# graspable and are only ever valid as a Place location or a Pour target.
SUPPORT_OBJECTS = {
    'box', 'crate', 'bowl', 'palette', 'container', 'mortar',
    'test tube holder', 'foam test tube holder',
}

# --- Language models ---------------------------------------------------------

# The scene photo is NOT sent to the model. Both stages work from the scene object
# list alone - the ids, colours, roles and x/y/z positions - which is also what the
# generated tree has to refer to. The photo is still shown in the window.
# Turning either of these back on also restores the sentences in the enrichment
# prompt that refer to the image (see modules/enrichment.py).
ENRICHMENT_MODEL = 'gpt-4o'
ENRICHMENT_TEMPERATURE = 0
ENRICHMENT_SEND_SCENE_IMAGE = False

BT_GENERATION_MODEL = 'gpt-4o'
BT_GENERATION_TEMPERATURE = 0
BT_GENERATION_SEND_SCENE_IMAGE = False

# Models the GUI offers in its dropdowns.
AVAILABLE_MODELS = ['gpt-4o', 'gpt-4o-mini', 'gpt-4.1', 'gpt-4.1-mini', 'gpt-5']

# --- Logging -----------------------------------------------------------------

CONSOLE_LOG_LEVEL = 'INFO'
FILE_LOG_LEVEL = 'DEBUG'
LOG_BACKUP_COUNT = 10
GUI_LOG_BUFFER = 4000  # log records kept in memory for the GUI log pane

# --- Behavior tree graph -----------------------------------------------------

GRAPH_EXPORT_DOT = True       # always write the .dot source next to the image
GRAPH_EXPORT_GRAPHVIZ = True  # also render with graphviz when the dot binary exists
GRAPH_EXPORT_FORMAT = 'png'   # graphviz output format: png or svg

# --- Graph colors (shared by the Pillow export and the GUI canvas) -----------

GRAPH_COLORS = {
    'background': '#1b1b1b',
    'sequence_fill': '#2c4a6e',
    'sequence_border': '#5b9bd5',
    'selector_fill': '#6e4a2c',
    'selector_border': '#d59b5b',
    'action_fill': '#2f4f3a',
    'action_border': '#6abf7b',
    'text': '#f2f2f2',
    'subtext': '#b9b9b9',
    'edge': '#8a8a8a',
}
