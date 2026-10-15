# Natural command → Behavior tree

Phase one of the behavior tree pipeline: a typed command becomes a scene-aware
command, then a `create_behavior_tree()` function, which is checked and drawn.
Planning and execution in the Unity simulator come later; nothing here talks to a
robot.

```
Scene  →  Command  →  Scene-aware command  →  Behavior tree  →  Syntax check  →  Graph
```

Everything runs in one window, and every module reports what it did, how long it took
and every file it produced.

## Running it

```bash
cd pipeline
../contextual-asr/venv/bin/python main.py
```

Pick one of the nine scenes, type a command, press **Run pipeline**.

The API key is read from `OPENAI_API_KEY`, or from
`contextual-asr/contextual-asr/API_KEY.txt` (the file must contain only the key).

## The modules

| Module | File | What it does |
|---|---|---|
| Scene | [modules/scene.py](modules/scene.py) | Loads a scene and gives every object a unique id (`transparent_test_tube_1`). Produces both the object list the generator sees and the scene dictionary the enrichment sees. |
| Command | [modules/command.py](modules/command.py) | The typed command. Isolated so the ASR can replace it later without touching anything else. |
| Scene-aware command | [modules/enrichment.py](modules/enrichment.py) | The contextual-asr post-processing, using the same five prompt files. Rewrites "the left tube" into the object that is actually there. |
| Behavior tree | [modules/generator.py](modules/generator.py) | Asks ChatGPT for `create_behavior_tree()` using [prompts/bt_generation_prompt.txt](prompts/bt_generation_prompt.txt). A declined command is reported as *declined*, not as an error. |
| Syntax check | [modules/tester.py](modules/tester.py) | Checks the generated function statically, then builds it in a sandbox. |
| Tree graph | [modules/graph.py](modules/graph.py) | Lays the tree out once and draws it on the canvas, to a PNG and to a `.dot` file. |

The four actions, the scene mechanism and all the structural rules come from the
manipulator prompt in the contextual-asr project: `Place`, `Pour`, `Shake`, `Close`.

## The scene photo is not sent to the model

Both model stages work from the scene object list alone — the ids, colours, roles and
x/y/z positions — which is also what the generated tree has to refer to. The photo is
still loaded and shown in the window, and still copied into the run directory; it is
simply not part of any request.

The contextual-asr enrichment prompt promises the model a picture in three places, so
when the photo is not sent those sentences are removed from the assembled prompt
(`without_image_references` in [modules/enrichment.py](modules/enrichment.py)). The
prompt *files* are left untouched, since contextual-asr shares them.

Dropping the photo made runs roughly twice as fast and about a third cheaper, with the
same trees coming out. To send it again, set `ENRICHMENT_SEND_SCENE_IMAGE` and
`BT_GENERATION_SEND_SCENE_IMAGE` back to `True` in [config.py](config.py); the removed
sentences come back with them.

## Where the scene data comes from

This project reads the nine scenes, their photos and the enrichment prompts from the
contextual-asr project beside it:

```
Contextual-asr/
├── contextual-asr/contextual-asr/prompt/   ← scenes, photos and enrichment prompts
└── pipeline/                               ← this repository
```

Nothing is duplicated, so there is one version of each file. If you clone this
repository on its own, point `CONTEXTUAL_ASR_DIR` in [config.py](config.py) at that
project, or copy `prompt/workspace_knowledge` and the five enrichment `.txt` files
next to it.

## What the syntax check checks

It is a *static* test. The only thing executed is the construction of the tree itself,
with the four actions replaced by inert stand-ins — which is the only way to prove the
function really returns a tree.

| Group | Checks |
|---|---|
| Syntax | the code parses; there is exactly one `create_behavior_tree`; nothing else at top level |
| Structure | the body is one `try/except` with the mandated `logging.error` line; the root is a `Sequence` named `Root`; every composite has `memory=True`; node names and variables are unique; no orphaned node, no node with two parents, no child that was never created |
| Arguments | every action gets exactly its own keyword arguments; `Shake(times=…)` is an integer literal; every node has a literal name |
| Scene | every object id exists in the scene, spelled exactly; locations are used as locations and graspable objects are grasped; a container holding liquid is closed before it is shaken |
| Build | the function loads, constructs, and returns a real `py_trees` node with the expected number of nodes |

A failed check marked *warning* is reported but does not stop the run. Only a failed
*error* check does. When the generated `try/except` swallows the real error, the tester
runs the body again without it so the message says what actually went wrong.

## What a run leaves behind

Every run writes a directory named after its id:

```
data/runs/2026-10-15_14-40-24_9186/
├── run.log                  every module together, in order
├── events.jsonl             the same records as JSON, one per line
├── logs/<module>.log        each module on its own
├── summary.json             command, scene, every stage's status and timing
├── scene.jpg                the scene photo (shown in the window, not sent to the model)
├── scene_objects.txt        the object list the generator was given
├── scene_knowledge.json     the dictionary the enrichment was given
├── command.txt              what was typed
├── enrichment/              system_prompt.txt · user_message.txt · raw_reply.txt
├── enriched_command.txt
├── generation/              system_prompt.txt · user_message.txt · raw_reply.txt
├── bt.py                    the tree as a runnable module
├── create_behavior_tree.py  just the generated function
├── tester_report.json       every check with its result and line number
├── bt_outline.txt           the tree as text
├── bt_graph.png             the tree as a picture
├── bt_graph.dot             the same graph as DOT source
└── bt_graph.json            the tree structure, used to redraw a past run
```

Global logs live in `data/logs/` — `debug.log`, `info.log` and `error.log`, rotated
daily. `error.log` alone tells you everything that has ever broken.

Any past run can be reopened from the dropdown at the top right of the window: its
panels, its code, its checks and its graph all come back.

## The graph

The layout is computed once and used three ways: the canvas in the window (zoom, pan,
click a node to see its arguments), `bt_graph.png` drawn with Pillow, and
`bt_graph.dot`. A sequence carries an arrow, a selector a question mark, and actions
are green boxes listing their arguments.

The `.dot` file is written always. When the graphviz `dot` binary is installed, a
`bt_graph_graphviz.png` is rendered from it as well:

```bash
brew install graphviz
```

Without it nothing is lost — the PNG and the canvas do not need graphviz.

## Settings

All of them are in [config.py](config.py): where the scenes and prompts are read from,
which models the stages use, the log levels, and the graph colours.

## Requirements

```bash
../contextual-asr/venv/bin/pip install -r requirements.txt
```

`py_trees` and `pydot` were the only additions to the contextual-asr environment.
