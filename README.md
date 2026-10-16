# Natural command → Behavior tree

A typed command becomes a scene-aware command, then a `create_behavior_tree()`
function, which is checked, judged, repaired until it is right, and drawn. Planning
and execution in the Unity simulator come later; nothing here talks to a robot.

```
Scene → Command → Scene-aware command → [ Behavior tree → Syntax check → Judge ] → Graph
```

The bracket is a loop. A rejected tree goes back to the generator with the reason, and
the run ends when a tree is accepted or a cap is reached.

**Nothing ever waits for a person.** The generator always returns a tree — an unclear
command is read the most reasonable way rather than questioned — and the semantic judge
is the only thing that decides whether the tree is right.

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
| Behavior tree | [modules/generator.py](modules/generator.py) | Asks ChatGPT for `create_behavior_tree()` using [prompts/bt_generation_prompt.txt](prompts/bt_generation_prompt.txt). It only translates: it never checks whether the plan is safe or complete. |
| Syntax check | [modules/tester.py](modules/tester.py) | Checks the generated function statically, then builds it in a sandbox. Nothing physical — only whether the code can run. |
| Semantic judge | [modules/judge.py](modules/judge.py) | Fills in the judgement form: accept or reject, which categories are wrong, and one sentence saying why. On a rejection that form becomes the generator's feedback. |
| Generation loop | [modules/loop.py](modules/loop.py), [modules/loop_stage.py](modules/loop_stage.py) | Runs the three above until a tree is accepted or a cap is reached, and keeps every attempt's artifacts apart. |
| Tree graph | [modules/graph.py](modules/graph.py) | Lays the tree out once and draws it on the canvas, to a PNG and to a `.dot` file. |

The four actions, the scene mechanism and all the structural rules come from the
manipulator prompt in the contextual-asr project: `Place`, `Pour`, `Shake`, `Close`.

## Who decides what

Each part has exactly one job, and they are deliberately kept apart.

| Part | Decides | Does not |
|---|---|---|
| Enrichment | Which scene object the user's words mean. | |
| Generator | What the command says to do, and in what order. | Whether the plan is safe, complete or well ordered. |
| Syntax check | Whether the code parses, builds, and uses ids that exist in their right role. | What the tree means. No physical rules. |
| Semantic judge | Whether the tree does what the user asked, in a physically possible way. | Write or repair trees. Node names and code style. |

A generator that shakes an open test tube because the command never mentioned a cap is
**intended** — the judge catches it and the loop repairs it. That split is the point of
the design: faults have to be able to reach the judge, so the generator is not allowed
to prevent them.

## What the "Enrich with the scene first" switch changes

Enrichment runs once, before the loop, and rewrites your command so it names the
objects that are actually in the scene — "the red container" becomes "the red box".
It is a separate model call with its own prompt; what reaches the two stages after it
is only the rewritten sentence.

**For the generator, nothing is added.** Its system prompt is identical either way —
the same generation prompt, the same scene object list. The command is *swapped*, not
supplemented:

```
Enrichment off →  COMMAND: Put the yellow block in the red container.
Enrichment on  →  COMMAND: Place the yellow cuboid in the red box.
```

The generator never learns that enrichment happened, or what you originally typed.

**For the judge, one line is added.** It always receives `ORIGINAL COMMAND:` with your
own words, and gains a second line when enrichment ran *and changed the text*:

```
ORIGINAL COMMAND:  Put the yellow block in the red container.
REWRITTEN COMMAND: Place the yellow cuboid in the red box.
BEHAVIOR TREE:
...
```

The judge is the only part that sees both. That is deliberate: the rewrite is another
model's guess, so a wrong mapping is one of the faults the judge is there to catch, and
its prompt tells it to judge against the original and treat the rewritten one as a hint.
If the rewrite comes back unchanged, the line is left out.

## The judgement form

The judge answers with JSON and nothing else, re-validated by `parse_judgement()` even
when the model returns structured output:

```json
{"verdict": "reject",
 "errors": ["missing_precondition"],
 "reason": "ShakeVialTwoTimes shakes transparent_vial while it is open and holds liquid."}
```

The six error codes, each shown to the generator as the form's own sentence:

| Code | Sentence |
|---|---|
| `goal_not_achieved` | The tree does not achieve the requested goal |
| `missing_action` | A required action is missing |
| `wrong_order` | Actions are in the wrong order |
| `wrong_object_or_location` | A wrong object or location is used |
| `missing_precondition` | A necessary precondition or check is missing |
| `not_feasible` | The task is not feasible for the robot |

An accept carrying errors, or a reject with no error or no reason, is refused and the
judge is asked again. **A judge that fails is never treated as an accept.**

## The caps, and how a run ends

All in [config.py](config.py), counted per run:

| Setting | Default | Meaning |
|---|---|---|
| `SYNTAX_FAILURE_LIMIT` | 3 | The run ends at the 3rd tree the syntax check rejects. A reply holding no code counts as one. |
| `JUDGE_REJECTION_LIMIT` | 3 | The run ends at the 3rd rejected tree, so the judge sees at most three. From the study design. |
| `JUDGE_FORMAT_RETRIES` | 2 | Extra judge calls when a reply is not a valid form. |

A run ends as `accepted`, `failed_judge_cap`, `failed_syntax_cap`, `judge_error` or
`error`. Syntax failures do not count toward the judge cap.

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
| Scene | every object id exists in the scene, spelled exactly; locations are used as locations and graspable objects are grasped |
| Build | the function loads, constructs, and returns a real `py_trees` node with the expected number of nodes |

A failed check marked *warning* is reported but does not stop the run. Only a failed
*error* check does. When the generated `try/except` swallows the real error, the tester
runs the body again without it so the message says what actually went wrong.

There are **no physical rules here**. "A container holding liquid is closed before it is
shaken" used to be a check and is now the judge's to make, so a `Shake` without a
`Close` passes this stage and reaches the judge. The rule is still computed as
`spill_label()` and written to `analysis_labels.json` per attempt, as an automatic
label for evaluating the judge later — it is never shown to the generator or the judge,
and it never changes a status.

## What a run leaves behind

Every run writes a directory named after its id:

Every run writes a directory named after its id, and **every attempt keeps its own
folder**, so a repaired tree never overwrites the one it replaces:

```
data/runs/2026-10-15_21-37-30_90bc/
├── run.log                  every module together, in order
├── events.jsonl             the same records as JSON, one per line
├── logs/<module>.log        each module on its own
├── summary.json             the loop's status, counters, every judgement form, the
│                            models, the caps and the timestamps
├── scene.jpg                the scene photo (shown in the window, not sent to the model)
├── scene_objects.txt        the object list the generator was given
├── scene_knowledge.json     the dictionary the enrichment was given
├── command.txt              what was typed
├── enrichment/              system_prompt.txt · user_message.txt · raw_reply.txt
├── enriched_command.txt
├── attempts/
│   ├── 01/
│   │   ├── generation/          system_prompt.txt · user_message.txt · raw_reply.txt
│   │   ├── create_behavior_tree.py
│   │   ├── tester_report.json   every check with its result and line number
│   │   ├── analysis_labels.json the automatic labels, for later analysis only
│   │   ├── judge_outline.txt    the tree exactly as the judge was shown it
│   │   ├── judge/01/            one folder per judge call
│   │   └── judge_form.json      the judgement form
│   └── 02/ …                    the repair, and its own judgement
├── bt.py                    the accepted tree as a runnable module
├── create_behavior_tree.py  just the accepted function
├── bt_graph.png             the accepted tree as a picture
├── bt_graph.dot             the same graph as DOT source
└── bt_graph.json            the tree structure, used to redraw a past run
```

Each attempt in `summary.json` carries a `ground_truth` field, left `null` on purpose.
It is filled in by hand with `"correct"` or `"faulty"` until the simulation exists —
without it the judge cannot be evaluated.

Global logs live in `data/logs/` — `debug.log`, `info.log` and `error.log`, rotated
daily. `error.log` alone tells you everything that has ever broken.

Any past run can be reopened from the dropdown at the top right of the window, and the
**Attempt** selector switches the Code, Checks, Judge and Tree graph tabs between that
run's attempts.

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
which models the generator and the judge use, the caps, the log levels, and the graph
colours. The window's two dropdowns override the two models per run.

## Tests

Ten cases drive the real loop with scripted model replies and the real syntax check —
acceptance, repair after a rejection, each cap, a reply holding no code, and an invalid
judgement form:

```bash
../contextual-asr/venv/bin/python -m pytest tests -q
```

## Requirements

```bash
../contextual-asr/venv/bin/pip install -r requirements.txt
```

`py_trees`, `pydot` and `pytest` were the only additions to the contextual-asr
environment.
