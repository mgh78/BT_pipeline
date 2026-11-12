# Natural command → Behavior tree

A typed command becomes a scene-aware command, then a behavior tree written in XML, which
is checked, built with py_trees, judged, repaired until it is right, and drawn. The tree
can then be **run on a mock world**: a plain-Python copy of the scene that applies the
physical rules, so you can watch, tick by tick, what every node does. Execution in the
Unity simulator comes later; nothing here talks to a robot.

```
Making a tree:   Scene → Command → Scene-aware command → [ Behavior tree → Syntax check → Judge ] → Graph
Running a tree:  bt.xml or attempts/NN/tree.xml → mock world of the scene → executor → trace
```

The bracket is a loop. A rejected tree goes back to the generator with the reason, and the
run ends when a tree is accepted or a cap is reached.

**Nothing ever waits for a person.** The generator always returns a tree (an unclear
command is read the most reasonable way rather than questioned), and the semantic judge is
the only thing that decides whether the tree is right.

**Making and running are separate.** A pipeline run makes, checks and judges a tree but
never runs it. Running is done afterwards, from the terminal (`run_tree.py`) or from the
window's **Execution** tab.

Everything runs in one window, and every module reports what it did, how long it took and
every file it produced.

---

## Contents

1. [Quick start](#quick-start)
2. [Words used in this README](#words-used-in-this-readme)
3. [What is where](#what-is-where)
4. [The window](#the-window)
5. [The modules of a pipeline run](#the-modules-of-a-pipeline-run)
6. [The trees are XML, built by py_trees](#the-trees-are-xml-built-by-py_trees)
7. [Generic trees: find and check nodes](#generic-trees-find-and-check-nodes)
8. [The blackboard and the `{key}` notation](#the-blackboard-and-the-key-notation)
9. [Where the grammar comes from](#where-the-grammar-comes-from)
10. [Who decides what](#who-decides-what)
11. [What the "Enrich with the scene first" switch changes](#what-the-enrich-with-the-scene-first-switch-changes)
12. [The baseline: Judge or Baseline](#the-baseline-judge-or-baseline)
13. [The generation loop, its caps, and how a run ends](#the-generation-loop-its-caps-and-how-a-run-ends)
14. [The judgement form](#the-judgement-form)
15. [What the judge sees on a later attempt](#what-the-judge-sees-on-a-later-attempt)
16. [What the generator is told when a tree comes back](#what-the-generator-is-told-when-a-tree-comes-back)
17. [What the syntax check checks](#what-the-syntax-check-checks)
18. [Running a tree on the mock world](#running-a-tree-on-the-mock-world)
19. [What a run leaves behind](#what-a-run-leaves-behind)
20. [The graph](#the-graph)
21. [The prompts](#the-prompts)
22. [The scenes](#the-scenes)
23. [The scene photo is not sent to the model](#the-scene-photo-is-not-sent-to-the-model)
24. [Settings](#settings)
25. [Logging](#logging)
26. [Tests](#tests)
27. [Requirements](#requirements)
28. [Branches](#branches)
29. [Known gaps](#known-gaps)

---

## Quick start

Everything runs in the contextual-asr virtual environment, from the `pipeline` folder.

```bash
cd ~/Desktop/Contextual-asr/pipeline
source ../contextual-asr/venv/bin/activate      # then "python" is the right Python
```

Without activating, write `../contextual-asr/venv/bin/python` instead of `python`. The
system `python3` does not have py_trees, and macOS has no plain `python` command.

| To… | Run |
|---|---|
| open the window | `python main.py` |
| run a run's accepted tree on the mock world | `python run_tree.py --run data/runs/<run id>` |
| …pausing after every tick | `python run_tree.py --run data/runs/<run id> --step` |
| run one attempt's tree | `python run_tree.py data/runs/<run id>/attempts/01/tree.xml --scene scene8` |
| run your latest run | `python run_tree.py --run data/runs/$(ls -t data/runs \| head -1) --step` |
| run the tests | `python -m pytest tests -q` |
| install the requirements | `pip install -r requirements.txt` |

In the window: pick one of the nine scenes, type a command, press **Run pipeline**.

The API key is read from the `OPENAI_API_KEY` environment variable, or from
`contextual-asr/contextual-asr/API_KEY.txt` (the file must contain only the key).

---

## Words used in this README

| Word | Meaning |
|---|---|
| **run** | One press of **Run pipeline**: one scene, one command, every attempt, in one folder `data/runs/<run id>/`. |
| **attempt** | One tree the generator wrote during a run. A run has 1 to 5 attempts (at most 2 syntax failures plus 3 judged trees); each keeps its own folder `attempts/NN/`. |
| **behavior tree** | A tree of nodes the robot runs from the top. Inner nodes decide the order; leaves act or check. |
| **node** | One element of the tree, one XML tag: `Sequence`, `FindOne`, `Place`, … |
| **composite** | A node with several children: `Sequence` or `Selector`. |
| **decorator** | A node that wraps exactly one child and changes how it runs or what it returns: `ForEach`, `Inverter`, `Retry`, `Repeat`, `Timeout`, `FailureIsSuccess`. |
| **leaf** | A node with no children: one of the four actions or the four find/check nodes. |
| **action** | A leaf that makes the robot do something: `Place`, `Pour`, `Shake`, `Close`. |
| **find node** | `FindOne` or `FindAll`: finds objects on the table by their properties and stores them on the blackboard. |
| **condition** | `HasProperty` or `HasCount`: succeeds or fails and changes nothing. |
| **status** | What a node returns when it runs: `SUCCESS`, `FAILURE` or `RUNNING` (not finished yet; run me again next tick). |
| **tick** | One pass over the tree from the root. A long task (a `ForEach` over five objects) takes several ticks. |
| **memory** | `memory="true"` on a `Sequence` or `Selector`: a child that returned `RUNNING` is resumed on the next tick instead of starting from the first child again. |
| **blackboard** | The py_trees shared store the nodes read and write while the tree runs: `/objects`, `/object`, `/palette`, … |
| **key** | The name of a blackboard entry. Written plain (`key="palette"`) where a node writes it, and `{palette}` where a node reads the object stored there. |
| **port** | A py_trees input that the XML parser wires to a blackboard key at build time. Every `{key}` argument is a port. |
| **generic tree** | A tree that never names a scene object. It describes the objects it needs by what the robot perceives and finds them while it runs, so the same tree works on any table. |
| **perception properties** | What the robot knows about each object: `type`, `color`, `liquid_color`, `graspable`, `holds_liquid`, `closed`, `marked` ([prompts/perception.txt](prompts/perception.txt)). |
| **enrichment** | The optional first model call that rewrites the command with the scene's object names. |
| **generator** | The model that writes the tree. It only translates the command; it never checks safety. |
| **syntax check** | The static check of the XML: can this tree be built, and does it follow the grammar? No physical rules. |
| **judge** | The model that decides whether a tree does what the user asked, in a physically possible way. |
| **baseline** | A run with the judge switched off: the first tree that passes the syntax check is the result. |
| **world** | Something a tree can act on. It answers "which objects have these properties?" and carries out actions. Today the mock world; later Unity. |
| **mock world** | The plain-Python world: a copy of one scene's objects plus the physical rules ([modules/mock_world.py](modules/mock_world.py)). |
| **executor** | `execute()` in [modules/executor.py](modules/executor.py): checks a tree, builds it for a world, ticks it to the end and records everything. |
| **trace** | What the executor records: for every tick, the nodes that ran, the blackboard reads and writes, the blackboard afterwards and the world's events. |
| **outcome** | The world's answer to an action: did it happen, why not, and did anything go wrong (`Outcome` in [modules/world.py](modules/world.py)). |
| **done** | An action that was carried out. |
| **refused** | An action the world would not carry out because a rule was broken. Nothing on the table changes. |
| **fault** | Something that went physically wrong although the action was carried out. Today only `spill`. |
| **registry** | The tag → class map the py_trees parser builds the leaves from. |

---

## What is where

```
pipeline/
├── main.py                  opens the window
├── run_tree.py              runs a tree on the mock world from the terminal
├── config.py                every path and setting, in one place
├── requirements.txt
├── core/
│   ├── pipeline.py          Stage, Pipeline, StageResult, StageStatus, Check, StageError
│   ├── run_context.py       RunContext: the run id and the run folder, writes artifacts
│   └── logging_setup.py     the log files, the per-run logs, the window's log buffer
├── modules/
│   ├── scene.py             load_scene(): the objects of a scene, with unique ids
│   ├── command.py           CommandStage: the typed command
│   ├── enrichment.py        EnrichmentStage: the scene-aware command
│   ├── llm.py               ask(): the one place that calls the OpenAI API
│   ├── prompt_files.py      load_prompt(): reads a prompt and its {{include: …}} lines
│   ├── generator.py         BTGenerator: asks for the tree; as_document() writes bt.xml
│   ├── xml_tree.py          extract_xml(), check_xml(), build_tree(): read, check, build XML
│   ├── tester.py            SyntaxTestStage: runs check_xml() and reports it
│   ├── judge.py             SemanticJudge: asks the judge, returns its form
│   ├── loop.py              run_generation_loop(): generator → check → judge, the caps
│   ├── loop_stage.py        GenerationLoopStage: runs the loop, writes attempts/ and bt.xml
│   ├── graph.py             TreeGraphStage: lays the tree out, the PNG, DOT and JSON
│   ├── bt_nodes.py          the 8 leaf node classes, REGISTRY and registry(world)
│   ├── world.py             the world interface: WorldObject, Outcome, World
│   ├── mock_world.py        MockWorld: a scene in Python, with the physical rules
│   └── executor.py          execute(): run a tree on a world, the trace, the text output
├── gui/
│   ├── app.py               the window and its controller
│   ├── stage_panel.py       one panel per pipeline module; the Checks table
│   ├── graph_view.py        the Tree graph tab's canvas
│   ├── log_view.py          the log pane along the bottom
│   ├── execution_view.py    the Execution tab
│   └── execution_text.py    the Execution tab's text (testable without the window)
├── prompts/                 the generation and judge prompts and their shared parts
├── tests/                   the test suite
├── update/                  task notes: what was changed and why, SCENES.md
└── data/                    runs and logs (not in git)
```

---

## The window

Open it with `python main.py`.

| Part | What it is |
|---|---|
| **Left column: Scene** | The scene menu, the scene photo, and the object list with ids, colours, roles and positions. The generator is never shown this list; the judge is. |
| **Middle column: the command** | The command box; the **Enrich with the scene first** switch (on by default); the **Judge / Baseline** selector; the tree and judge model menus and their reasoning-effort menus; **Run pipeline**. |
| **Middle column: Pipeline modules** | One panel per stage (Scene, Command, Scene-aware command, Generation loop, Tree graph): a coloured dot, what it did, how long it took. Open a panel to see its details and a button for every file it wrote. |
| **Top right: run menu** | Reopens any past run from `data/runs/`. **Run folder** opens the run's folder. |
| **Right column: Attempt menu** | Picks which attempt of the run the tabs below show: `1 · judge rejected`, `2 · judge accepted`, `1 · not judged` (baseline), `1 · syntax failed`, `1 · no code in the reply`. |
| **Tree graph tab** | The attempt's tree on a canvas: zoom with −, + or the mouse wheel, **Fit**, drag to pan, click a node to see its arguments. **Open image** opens `bt_graph.png`. |
| **XML tab** | The attempt's XML, with **Copy**. |
| **Checks tab** | Every syntax check with its result and line number. |
| **Judge tab** | The analysis, the verdict, the errors and the reason, and the tree outline the judge was shown. |
| **Execution tab** | **Run tree** runs the chosen attempt's tree on a fresh mock world of the run's scene and shows the whole execution (see [The Execution tab](#the-execution-tab)). |
| **Bottom: Log** | Every module's log as it happens. Filter by module and level; **Log folder** opens `data/logs/`. |

---

## The modules of a pipeline run

| Module | File | What it does |
|---|---|---|
| Scene | [modules/scene.py](modules/scene.py) | Loads a scene and gives every object a unique id (`transparent_test_tube_1`). Produces the object list the judge sees and the scene dictionary the enrichment sees. |
| Command | [modules/command.py](modules/command.py) | The typed command. Isolated so the ASR can replace it later without touching anything else. |
| Scene-aware command | [modules/enrichment.py](modules/enrichment.py) | The contextual-asr post-processing, with the same five prompt files. Rewrites "the left tube" into the object that is actually there. Optional. |
| Behavior tree | [modules/generator.py](modules/generator.py) | Asks the model for the tree as an XML document, using [prompts/bt_generation_prompt.txt](prompts/bt_generation_prompt.txt). It only translates: it never checks whether the plan is safe or complete. |
| Syntax check | [modules/xml_tree.py](modules/xml_tree.py), [modules/tester.py](modules/tester.py) | Reads the XML with its line numbers, checks it, then builds it with the py_trees XML parser. Nothing physical: only whether the tree can be built and follows the grammar. |
| Semantic judge | [modules/judge.py](modules/judge.py) | Fills in the judgement form: accept or reject, the problems in its own words, and why. On a rejection that form becomes the generator's feedback. |
| Generation loop | [modules/loop.py](modules/loop.py), [modules/loop_stage.py](modules/loop_stage.py) | Runs the three above until a tree is accepted or a cap is reached, and keeps every attempt's files apart. |
| Tree graph | [modules/graph.py](modules/graph.py) | Lays the tree out once and draws it on the canvas, to a PNG and to a `.dot` file. |

The generator, the syntax check and the judge are not separate panels in the window: they
run inside the **Generation loop** stage. Every model call goes through `llm.ask()`
([modules/llm.py](modules/llm.py)), which saves the exact system prompt, user message and
raw reply of the call in the run folder.

---

## The trees are XML, built by py_trees

The generator writes the tree in the BehaviorTree.CPP XML format, and py_trees 2.6 builds
it with its XML parser (`py_trees.parsers.behaviour_tree_xml.parse_behaviour_tree_xml`).

```xml
<root main_tree_to_execute="MainTree">
  <BehaviorTree ID="MainTree">
    <Sequence name="Root" memory="true">
      <FindOne name="FindBlueBox" key="box" type="box" color="blue"/>
      <FindAll name="FindPackages" key="packages" type="package"/>
      <ForEach name="ForEachPackage" source_key="packages" target_key="package">
        <Place name="PlacePackageInBox" obj="{package}" location="{box}"/>
      </ForEach>
    </Sequence>
  </BehaviorTree>
</root>
```

**The frame** is always `<root main_tree_to_execute="MainTree">` holding one
`<BehaviorTree ID="MainTree">`, which holds one root node: `<Sequence name="Root"
memory="true">`. Every node has a unique `name` of letters and digits.

**The nodes the grammar allows:**

| Node | Kind | Arguments | What it does |
|---|---|---|---|
| `Sequence` | composite | `name`, `memory` | runs its children in order and stops at the first failure |
| `Selector` | composite | `name`, `memory` | tries its children in order until one succeeds |
| `ForEach` | decorator | `source_key`, `target_key` | runs its child once for every item of a list |
| `Inverter` | decorator | — | "not": SUCCESS becomes FAILURE and back; only around `HasProperty` or `HasCount` |
| `Retry` | decorator | `num_failures` | runs its child again after a failure, up to `num_failures` times |
| `Repeat` | decorator | `num_success` | runs its child until it has succeeded `num_success` times |
| `Timeout` | decorator | `duration` (optional) | fails its child if it is still running after `duration` seconds |
| `FailureIsSuccess` | decorator | — | turns its child's FAILURE into SUCCESS |
| `Place` | action | `obj`, `location` | puts `obj` at `location` |
| `Pour` | action | `source`, `target` | pours the liquid in `source` into `target` |
| `Shake` | action | `obj`, `times` | shakes `obj` `times` times |
| `Close` | action | `obj`, `closing_obj` | closes `obj` with the cap `closing_obj` |
| `FindOne` | find | `key`, properties, `position`, `nth` | stores one object under `key` |
| `FindAll` | find | `key`, properties, `position`, `limit` | stores a list of objects under `key` |
| `HasProperty` | condition | `obj`, `property`, `value` | succeeds when the object has that property value |
| `HasCount` | condition | `key`, `count`, `comparison` | succeeds when a `FindAll` list has that many objects |

The decorators allowed are `GRAMMAR_DECORATORS` in [config.py](config.py).

**Who builds what.** The parser builds `Sequence`, `Selector` and the py_trees decorators
from their tag names itself; those are py_trees' own classes. The four actions and the
four find/check nodes are this project's classes in [modules/bt_nodes.py](modules/bt_nodes.py),
written as py_trees *ports* nodes (`py_trees.ports.BehaviourWithPorts`), because the
parser only builds leaves of that kind. They are passed to the parser as an explicit
`node_registry`, so it builds nothing else; `"auto"` is never used.

**How an attribute reaches a node.** An object argument such as `obj="{rack}"` is an
input port: the parser wires it to the blackboard key `/rack`. Every other attribute is a
constructor argument, converted to the type the class annotates (`times="2"` becomes `2`,
`marked="False"` becomes `False`).

**Names.** The parser prefixes every node name with its parents' names
(`Root.ForEachFlask.PlaceFlask`). After building, the nodes are renamed back to the names
in the XML (`_label()` in [modules/xml_tree.py](modules/xml_tree.py)), which the check
keeps unique. Each built node also gets an `arguments` dict with its XML attributes, which
the graph and the judge outline show.

**The parser accepts more than the prompt allows**, and its messages have no line
numbers. So [modules/xml_tree.py](modules/xml_tree.py) checks the document first, and
only a tree that passes is handed to the parser.

---

## Generic trees: find and check nodes

The generator writes **generic** trees: the same tree does the task on any table. It is
not shown the scene's objects and never names one. Instead the tree describes the objects
it needs by what the robot perceives, finds them while it runs, and the rest of the tree
refers to them through the blackboard.

**Perception properties** ([prompts/perception.txt](prompts/perception.txt), and the same
lists in [config.py](config.py)):

| Property | Values | Setting |
|---|---|---|
| `type` | cube, cuboid, package, test tube, test tube cap, test tube holder, foam test tube holder, measuring cylinder, bottle, cup, bowl, box, crate, palette, container, mortar | `PERCEPTION_TYPES` |
| `color` | a lowercase colour name; glass is `transparent` | `PERCEPTION_COLOR_PROPERTIES` |
| `liquid_color` | the liquid's colour, `""` when it holds none | `PERCEPTION_COLOR_PROPERTIES` |
| `graspable` | `True` for objects the robot can pick up; `False` for boxes, crates, bowls, palettes, containers, mortars and holders | `PERCEPTION_BOOLEAN_PROPERTIES` |
| `holds_liquid` | `True` when it contains liquid | `PERCEPTION_BOOLEAN_PROPERTIES` |
| `closed` | `True` when it is closed with a cap | `PERCEPTION_BOOLEAN_PROPERTIES` |
| `marked` | `True` when it carries a marker, such as a marked package | `PERCEPTION_BOOLEAN_PROPERTIES` |

**The four find and check nodes:**

- `FindOne(name, key, <properties>, position, nth)` stores the nth object (default 1) that
  has all the properties under `key`. It **fails** when fewer than `nth` objects match.
  `position` (`leftmost`, `rightmost`, `nearest`, `farthest`; `FIND_POSITIONS`) and `nth`
  pick among several: "the second box from the left" is `position="leftmost" nth="2"`.
- `FindAll(name, key, <properties>, position, limit)` stores the list of all matching
  objects, or only the first `limit`. It **never fails**; the list can be empty. A
  `ForEach` loops over it, or a `HasCount` counts it.
- `HasProperty(name, obj, property, value)` checks one object while the tree runs, for
  "if …, otherwise …" commands.
- `HasCount(name, key, count, comparison)` succeeds when a `FindAll` list holds `count`
  objects. `comparison` is `"exactly"` (the default), `"at least"` or `"at most"`
  (`HAS_COUNT_COMPARISONS`). `key` is the plain key of a `FindAll`, never a `{key}`, a
  `FindOne` key or a `ForEach` target.

**The order objects are found in.** Without `position`, scan order: left to right (lowest
`y` first), and among objects with the same `y`, near to far (lowest `x` first). With
`position`: `leftmost` is lowest `y` first, `rightmost` highest `y` first, `nearest` lowest
`x` first, `farthest` highest `x` first. Ties are broken by the other axis (see
[Finding objects](#finding-objects)).

**Choices.** `Inverter` means "not" and may only wrap `HasProperty` or `HasCount`. A
choice is a `Selector` with one branch per case, each starting with its condition;
"otherwise" is the condition again inside an `Inverter`, and a choice with no "otherwise"
ends in a branch made only of inverted conditions.

**Placement.** Find nodes can stand anywhere: inside a branch, inside a `ForEach`, or
after an action, so an object is found right before it is used. A key must only be stored
before it is used, in the order the tree runs.

**Only the judge sees the scene.** It is shown the scene's objects, so it can work out what
each find node finds on this table, and it is asked whether the tree's logic would also be
right on other tables. Its reason must not list the objects or their ids, so the
generator's tree stays generic. Keep enrichment off for these runs: enrichment rewrites the
command with the scene's object names.

**A known limit.** There is no "the same property as another object" relation. A command
like "put each block in the box of the matching colour" makes the generator write one
branch per colour in the perception list, which gives very large trees.

---

## The blackboard and the `{key}` notation

The blackboard is py_trees' shared store. Find nodes and `ForEach` **write** to it; actions
and conditions **read** from it. In the XML there are two spellings:

| In the XML | Means | Used by |
|---|---|---|
| `{key}` (braces) | the object stored under `key`, read when the node runs (a port) | `obj`, `location`, `source`, `target`, `closing_obj` of the actions; `obj` of `HasProperty` |
| `key` (plain) | the name of a blackboard entry | where `FindOne`/`FindAll` store (`key`) and where `ForEach` writes each item (`target_key`); which list `ForEach` reads (`source_key`) and `HasCount` counts (`key`) |

```xml
<FindOne name="FindPalette" key="palette" type="palette"/>              <!-- WRITES /palette -->
<Place name="PlaceMarked" obj="{object}" location="{palette}"/>          <!-- READS /object and /palette -->
```

In the trace you see both sides:

```
WRITE /palette = brown_palette by FindPalette
READ  /palette = brown_palette by PlaceMarked
```

**The graph uses one rule:** braces always mean "read from the blackboard". So the graph
also draws the two keys that are read but written plain in the XML in braces:
`source_key = {objects}` on a `ForEach` and `key = {objects}` on a `HasCount`. That is
display only: the XML, the checks and the judge's outline keep them plain.

---

## Where the grammar comes from

The grammar the generation prompt gives the model (the composites `Sequence` and
`Selector` and the decorators) is based on the **py_trees** library:
<https://github.com/splintered-reality/py_trees>. The node names, their arguments and what
each one does follow py_trees 2.x (checked against the installed 2.6.0). Only the four
actions and the four find/check nodes are this project's own.

**The prompt is the grammar, and the syntax check enforces it.** `GRAMMAR_DECORATORS` in
[config.py](config.py) names the py_trees decorators the prompt allows. A tag the prompt
does not name, such as `OneShot`, `Parallel` or `SubTree`, is refused as "not allowed"
before the tree is built, even though the py_trees XML parser would build it.
[modules/xml_tree.py](modules/xml_tree.py) knows how to check every decorator in its
`DECORATORS` table, so widening the grammar is two edits: add the decorator to the prompt
and to `GRAMMAR_DECORATORS`. If you change one and not the other, the syntax check and the
prompt disagree.

---

## Who decides what

Each part has exactly one job, and they are deliberately kept apart.

| Part | Decides | Does not |
|---|---|---|
| Enrichment | Which scene object the user's words mean. | |
| Generator | What the command says to do, and in what order. | Whether the plan is safe, complete or well ordered. |
| Syntax check | Whether the XML can be built, uses only the grammar, and stores every key before it is used. | What the tree means. No physical rules. |
| Semantic judge | Whether the tree does what the user asked, in a physically possible way. | Write or repair trees. Judge node names or style. |
| Mock world | What happens on the table when the tree runs: what is found, what is refused, what goes wrong. | Whether the run was the right thing to do. |

A generator that shakes an open test tube because the command never mentioned a cap is
**intended**: the judge catches it and the loop repairs it. That split is the point of the
design: mistakes have to be able to reach the judge, so the generator is not allowed to
prevent them.

---

## What the "Enrich with the scene first" switch changes

Enrichment runs once, before the loop, and rewrites your command so it names the objects
that are actually in the scene: "the red container" becomes "the red box". It is a
separate model call with its own prompt; what reaches the stages after it is only the
rewritten sentence.

**For the generator, nothing is added.** Its system prompt is identical either way. The
command is *swapped*, not supplemented:

```
Enrichment off →  COMMAND: Put the yellow block in the red container.
Enrichment on  →  COMMAND: Place the yellow cuboid in the red box.
```

The generator never learns that enrichment happened, or what you originally typed.

**For the judge, one line is added.** It always receives `ORIGINAL COMMAND:` with your own
words, and gains a second line when enrichment ran *and changed the text*:

```
ORIGINAL COMMAND:  Put the yellow block in the red container.
REWRITTEN COMMAND: Place the yellow cuboid in the red box.
BEHAVIOR TREE:
...
```

The judge is the only part that sees both. The rewrite is another model's guess, so a
wrong mapping is one of the mistakes the judge is there to catch, and its prompt tells it
to judge against the original and treat the rewritten one as a hint. If the rewrite comes
back unchanged, the line is left out.

**Keep enrichment off for generic trees.** It resolves the command against today's scene
and puts the scene's object names into it, so the generator would no longer write a
generic tree.

---

## The baseline: Judge or Baseline

The **Judge / Baseline** selector under the command turns the judge off. The baseline is
what the judged runs are compared against, so everything before the judge stays identical:
same scene, same enrichment, same generation prompt, same syntax check.

With the judge off the syntax repair still runs: a tree that fails the syntax check is sent
back to the generator with the errors, exactly as in a judged run. The only thing missing
is the judge.

| | Judge | Baseline |
|---|---|---|
| A failed syntax check | sent back with the errors, up to 3 trees | the same |
| A tree that passes the syntax check | goes to the judge | **is the result** |
| A rejected tree | sent back with the judge's form | — |
| Generator calls | up to 3 syntax failures and up to 3 rejections | up to 3, all for syntax failures |
| Final status | `accepted`, `failed_judge_cap`, `failed_syntax_cap`, `judge_error` | `no_judge` or `failed_syntax_cap` |

So a baseline run shows what the generator produces once its tree can be built, including
the mistakes the judge would have caught. Running a baseline tree in the Execution tab
shows what those mistakes do on the table.

`summary.json` records `loop.judge_enabled` for every run. The default is `JUDGE_ENABLED`
in [config.py](config.py); the selector overrides it per run.

---

## The generation loop, its caps, and how a run ends

`run_generation_loop()` in [modules/loop.py](modules/loop.py), driven by
`GenerationLoopStage` in [modules/loop_stage.py](modules/loop_stage.py):

1. Send the generator the command (and, on a repair, the previous tree and its problems).
2. Take the XML out of the reply (`extract_xml()`). No XML at all counts as a syntax
   failure, and the generator is asked again.
3. Run the syntax check. On failure, send the errors back (step 1).
4. Baseline: stop here; the tree is the result (`no_judge`).
5. Judge: send the judge the command, the tree as an outline, and its own earlier
   judgements. A reply that is not a valid form is asked again, up to
   `JUDGE_FORMAT_RETRIES` times.
6. `accept` → the run ends (`accepted`). `reject` → the form goes back to the generator
   (step 1).

The caps, all in [config.py](config.py) and counted per run:

| Setting | Default | Meaning |
|---|---|---|
| `SYNTAX_FAILURE_LIMIT` | 3 | The run ends at the 3rd tree the syntax check rejects. A reply holding no tree counts as one. |
| `JUDGE_REJECTION_LIMIT` | 3 | The run ends at the 3rd rejected tree, so the judge sees at most three. From the study design. |
| `JUDGE_FORMAT_RETRIES` | 2 | Extra judge calls when a reply is not a valid form. |

Syntax failures do not count toward the judge cap.

| Final status | Meaning |
|---|---|
| `accepted` | the judge accepted a tree; it is saved as `bt.xml` |
| `no_judge` | baseline: the first tree that passed the syntax check; saved as `bt.xml` |
| `failed_judge_cap` | the judge rejected 3 trees |
| `failed_syntax_cap` | 3 trees (or replies without a tree) failed the syntax check |
| `judge_error` | the judge never returned a valid form. **A judge that fails is never treated as an accept.** |
| `error` | something outside the loop failed |

---

## The judgement form

The judge answers with JSON and nothing else, re-validated by `parse_judgement()` even
when the model returns structured output:

```json
{"analysis": "The tree has every requested action, but Shake runs while the vial is open.",
 "verdict": "reject",
 "errors": ["vial is shaken while open"],
 "reason": "ShakeVialTwoTimes shakes the vial stored under vial while it is open and holds liquid."}
```

`analysis` is the first field on purpose. With structured output the model writes the
fields in the order of the schema, so it works through its checks before it commits to a
`verdict`. The analysis is saved in each attempt's `judge_form.json` and shown at the top
of the Judge tab, but it is **not** sent to the generator: the feedback is the errors and
the reason.

`errors` is a list of short phrases in the judge's own words. There is no fixed set of
categories.

A form without exactly the four keys, with an empty analysis, an accept carrying errors,
or a reject with no error or no reason, is refused, and the judge is asked again.

---

## What the judge sees on a later attempt

Every tree is a new judge call, but from the second judged tree on the message also carries
an `EARLIER JUDGEMENTS:` block before the `BEHAVIOR TREE:`: for each tree the judge already
judged in this run, the attempt number, the tree as an outline, and the verdict, errors and
reason it gave. The analysis is not repeated, and a tree that failed the syntax check is not
listed, because the judge never saw it. The judge prompt says these are for reference and
that the new tree is judged on its own merits. The block is saved with the rest of the
message in `attempts/NN/judge/01/user_message.txt`.

The outline the judge reads comes from `outline_for_judge()` in
[modules/loop.py](modules/loop.py): one node per line, its type, its arguments exactly as
in the XML, and its name in brackets, children indented.

---

## What the generator is told when a tree comes back

**The system prompt never changes.** On every attempt the generator gets the identical
generation prompt. All the feedback goes into the **user message**:

```
COMMAND: shake the left test tube 3 times
PREVIOUS TREE:
<root main_tree_to_execute="MainTree">
  <BehaviorTree ID="MainTree">
    <Sequence name="Root" memory="true">
      <FindOne name="FindLeftTube" key="tube" type="test tube" position="leftmost"/>
      <Shake name="ShakeLeftTube" obj="{tube}" times="3"/>
    </Sequence>
  </BehaviorTree>
</root>
REVIEWER FINDINGS:
Problems: Shake runs while the tube is open.
Reason: ShakeLeftTube shakes the tube stored under tube while it is open and holds liquid, so the liquid will spill; it must be closed with a test tube cap first.
```

| Part | Where it comes from |
|---|---|
| `COMMAND:` | the same every attempt: the enriched command, or the typed one |
| `PREVIOUS TREE:` | the exact XML of the tree that was sent back |
| `Problems:` | the judge's `errors` phrases, verbatim |
| `Reason:` | the judge's explanation, verbatim |

The generator learns *what* is wrong and *why*, in the judge's words. It never sees the
analysis, the JSON, or the judge's prompt.

A failed syntax check uses the same shape, with `SYNTAX CHECK ERRORS:` in place of
`REVIEWER FINDINGS:` and each blocking check listed with its line number. A reply that held
no XML tree has no tree to send back, so it gets the demand alone:

```
COMMAND: shake the left test tube 3 times
Your reply contained no ```xml block with the tree. Return the tree.
```

**Only the last tree is sent.** On the third attempt the generator sees the second tree
and the second set of findings, not the whole history.

---

## What the syntax check checks

It is a *static* test: nothing runs. `check_xml()` in [modules/xml_tree.py](modules/xml_tree.py)
reads the document with its line numbers and checks it; only a tree that passes every
error check is handed to the py_trees XML parser, built with `bt_nodes.REGISTRY`, the node
classes **without a world**. The build proves the document really is a tree; the built
nodes cannot be ticked (see [The nodes act on a world](#the-nodes-act-on-a-world)).

| Group | Checks |
|---|---|
| Syntax | the reply is well-formed XML; it is a `<root main_tree_to_execute="MainTree">` holding exactly one `<BehaviorTree ID="MainTree">` with one root node; nothing but tags between the tags (a warning) |
| Structure | the root is a `Sequence` named `Root`; only the tags the prompt allows; no composite turns `memory` off, and a missing `memory="true"` is a warning (py_trees then uses true); a composite has children, a decorator exactly one, a leaf none; node names are unique across the tree; names are PascalCase (a warning); an `Inverter` wraps only `HasProperty` or `HasCount` |
| Arguments | every node gets exactly its own attributes; `times`, `num_failures`, `num_success` are whole numbers of 1 or more and `duration` a number above 0; every node has a name of letters and digits (no dots: the parser uses them to join names) |
| Objects | find nodes use only the properties and values in `PERCEPTION_*` (`type` from the closed list, colours lowercase, the rest `True`/`False`); `position` is one of `FIND_POSITIONS`; `nth` and `limit` are whole numbers of 1 or more; every key is a plain name stored once; every object argument is a `"{key}"` stored by a find node that runs earlier, or the `target_key` of a `ForEach` it sits inside; a `FindAll` list is only looped over or counted, and a `FindOne` object is never looped over; `HasCount` names the plain key of a `FindAll`, its `count` is a whole number of 0 or more and its `comparison` one of `HAS_COUNT_COMPARISONS`; curly braces appear only in object references |
| Build | the py_trees XML parser builds the tree, and the built tree holds every node the XML declares |

A failed *warning* is reported but does not stop the run; only a failed *error* does.
Every attempt's results are saved in `attempts/NN/tester_report.json` and shown in the
Checks tab.

There are **no physical rules here**. "A container holding liquid is closed before it is
shaken" is the judge's to make, so a `Shake` without a `Close` passes this stage and
reaches the judge.

---

## Running a tree on the mock world

A pipeline run never runs its tree. Running is a separate step: the executor takes an XML
tree and a world, ticks the tree to the end, and records what every node did.

```
XML ──► check_xml() ──► Blackboard.clear() ──► build_tree(xml, registry(world)) ──► tick, tick, tick… ──► result
                                                                    │                       │
                                                                    ▼                       ▼
                                                            nodes ask the world      trace of every tick
```

### The world interface

[modules/world.py](modules/world.py) defines what any world must offer. The tree's nodes
only ever talk to this interface, so the mock world and, later, Unity can be swapped
without changing the nodes.

**`WorldObject`**: one object on the table. Its field names are the perception property
names, so a node can read a property with `getattr(obj, "marked")`.

| Field | Meaning |
|---|---|
| `id` | the scene id, e.g. `white_marked_package_1` |
| `type`, `color`, `liquid_color` | as in [the perception properties](#generic-trees-find-and-check-nodes) |
| `graspable`, `holds_liquid`, `closed`, `marked` | `True` / `False` |
| `position` | `{'x', 'y', 'z'}` in metres |
| `on` | the id of the object it stands on or in; `None` on the table |
| `closed_by` | the id of the cap that closes it |
| `spilled` | liquid was spilled from it |

It prints as its id, so the blackboard stays readable, and `as_dict()` gives it as JSON.

**`Outcome`**: the world's answer to an action.

| Field | Meaning |
|---|---|
| `action_happened` | `True` when the action was carried out; `False` when it was refused, and then nothing changed |
| `reason` | for a refusal, why, in one sentence that names the objects; for a fault, what went wrong |
| `fault` | something that went physically wrong although the action was carried out (`"spill"`); `''` otherwise |

**`World`**: the methods.

| Method | What it does |
|---|---|
| `perceive(properties, position=None)` | every object that has all the properties, in order |
| `matches(obj, properties)` | `True` when `obj` has all the properties, by the same rule as `perceive` |
| `place(obj, location)`, `pour(source, target)`, `shake(obj, times)`, `close(obj, closing_obj)` | carry out an action; return an `Outcome` |
| `snapshot()` | the whole table as JSON-ready data: every object, and every fault so far |
| `take_events()` | the actions carried out since the last call, oldest first, then forgets them |

### The mock world

`MockWorld` in [modules/mock_world.py](modules/mock_world.py) keeps a list of
`WorldObject`s and changes them as actions run. `MockWorld.from_scene(load_scene("scene6"))`
builds one from a scene; every call makes **fresh copies**, so two worlds never share an
object, and the scene files are never changed.

**From a scene object to a `WorldObject`** (`from_scene_object()`):

| Field | From the scene |
|---|---|
| `type` | the object's name with the word `marked` removed (`marked package` → `package`) |
| `marked` | `True` when the name contains `marked` |
| `color`, `liquid_color` | the scene's colours, lowercase; `liquid_color` is `''` when it holds no liquid |
| `graspable` | `False` for the role `valid location` (`SUPPORT_OBJECTS` in [config.py](config.py)) |
| `holds_liquid` | `True` when the scene gives it a liquid |
| `closed` | `False`: at the start nothing is closed |
| `on` | from `INITIAL_ON`: the scene8 test tubes start in `grey_test_tube_holder`, because the scene files do not record it. Every other object starts with `None`. |

#### Finding objects

`perceive()` keeps the objects for which `matches()` is true, then sorts them:

- **Colours match loosely** (`color` and `liquid_color` only): a colour matches when it is
  equal, or when the object's colour **ends with it as a whole word**, ignoring case. So
  `red` finds `transparent red`, `green` finds `dark green`, but `transparent` does not
  find `transparent red`, and `red` does not find `infrared`. `''` matches only `''`.
- **Everything else must be equal**: `type`, and `True`/`False` as booleans.
- **A property no object has** matches nothing. **No properties at all** matches every
  object, which is why `FindAll key="objects"` on its own also finds boxes and palettes.
- **The order** (`ORDERS`), with a second key so a tie always has the same answer:

| `position` | Sort by |
|---|---|
| none (scan order) | `y`, then `x` |
| `leftmost` | `y`, then `x` |
| `rightmost` | `-y`, then `x` |
| `nearest` | `x`, then `y` |
| `farthest` | `-x`, then `y` |

#### Three results of an action

Every action ends in one of three ways:

| Result | `Outcome` | The table | Shown as | Node status |
|---|---|---|---|---|
| **done** | `action_happened=True` | changed as intended | `done` | SUCCESS |
| **done with a fault** | `action_happened=True, fault="spill"` | changed, and something went wrong | `done, FAULT: spill` (red) | SUCCESS, or FAILURE when `MOCK_SPILL_FAILS_ACTION = True` |
| **refused** | `action_happened=False`, reason | **nothing changed** | `refused — <reason>` (red) | FAILURE |

A **refusal** means the action could not take place. A **fault** means it took place but
caused a mess. The world always reports what really happened; the action node decides what
a fault means for its status.

#### The rules: when an action is refused

Each action checks its rules in order and refuses with the **first** one that is broken.
The tables are at the top of [modules/mock_world.py](modules/mock_world.py). Every action
also refuses an object id that is not on the table ("… is not on the table").

**`Place(obj, location)`** (`PLACE_RULES`). Effect: `obj.on = location.id`, and `obj` takes
the location's position.

| Rule | Refused with |
|---|---|
| `obj` is graspable | `<obj> is fixed and cannot be grasped` |
| `location` is not graspable | `<location> is not a place to put things` |
| they are different objects | `<obj> cannot be placed on itself` |
| `obj` is not a cap closing something | `<obj> closes <other> and cannot be moved on its own` |

**`Pour(source, target)`** (`POUR_RULES`). Effect: the target holds the source's liquid
(`"mixed"` when it already held a different colour); the source is empty.

| Rule | Refused with |
|---|---|
| `source` is graspable | `<source> is fixed and cannot be grasped` |
| `source` holds liquid | `<source> holds no liquid` |
| `source` is not closed | `<source> is closed and cannot be poured from` |
| they are different objects | `<source> cannot be poured into itself` |
| `target` is a container: not graspable, or a type in `POURABLE_INTO` (measuring cylinder, test tube, bottle, cup, bowl) | `<target> is not a container` |
| `target` is not closed | `<target> is closed; nothing can be poured into a closed container` |

**`Shake(obj, times)`** (`SHAKE_RULES`). Effect: none, unless it spills (below).

| Rule | Refused with |
|---|---|
| `obj` is graspable | `<obj> is fixed and cannot be grasped` |
| `times` is a whole number of 1 or more (`True` is not) | `<obj> cannot be shaken <times> times; times must be a whole number of 1 or more` |

**`Close(obj, closing_obj)`** (`CLOSE_RULES`). Effect: `obj.closed = True`,
`obj.closed_by = closing_obj.id`, and the cap's `on` is `obj`.

| Rule | Refused with |
|---|---|
| `closing_obj` is a cap that fits `obj` (`CAPS_FIT`: a test tube cap fits a test tube) | `<closing_obj> is not a cap or lid that fits <obj>` |
| `closing_obj` is graspable | `<closing_obj> is fixed and cannot be grasped` |
| `obj` is not already closed | `<obj> is already closed` |
| the cap does not already close another object | `<closing_obj> already closes another container; one cap closes one container` |

#### Faults

There is one fault today: **`spill`**. Shaking an object that holds liquid and is not
closed sets `spilled = True` and returns
`Outcome(action_happened=True, fault="spill", reason="<obj> was shaken while open and spilled")`.
It follows the first physical fact in
[prompts/judge_physical_facts.txt](prompts/judge_physical_facts.txt). Every fault is kept
in the world's `faults` list for the whole run, and `snapshot()["faults"]` returns it. A
spilled object still holds its liquid.

`MOCK_SPILL_FAILS_ACTION` in [config.py](config.py) decides what an action node makes of a
fault: `False` (default), the node succeeds; `True`, it fails. Either way the world reports
the fault. That is a question for the supervisor.

So a tree can end in **SUCCESS and still have a fault**: shaking an open tube is done, but
the liquid is on the table.

### The nodes act on a world

The leaf classes in [modules/bt_nodes.py](modules/bt_nodes.py) really act: each one's
`act()` asks the world. The world reaches a node through its **class**:

- `REGISTRY` is the plain tag → class map, with `world = None`. The syntax check builds with
  it and never ticks. Ticking a node without a world raises
  `RuntimeError: … was built without a world; build the tree with bt_nodes.registry(world)`.
- `registry(world)` makes, for every node class, a subclass carrying `world` as a class
  attribute. The executor builds with it, so every node py_trees creates can use
  `self.world`. It must be a real subclass and not `functools.partial`: py_trees converts
  `marked="False"` to `False` and `limit="2"` to `2` by reading the class's and its parents'
  `__init__`, which a partial hides.

| Node | What `act()` does | Status |
|---|---|---|
| `FindOne` | `world.perceive(properties, position)`, then writes the nth object to the blackboard under `key` | FAILURE when fewer than `nth` match |
| `FindAll` | `world.perceive(...)`, then writes the list (or the first `limit`) under `key` | always SUCCESS, even for `[]` |
| `HasProperty` | reads `obj` through its port; `True`/`False` values become booleans; `world.matches(obj, {property: value})` | SUCCESS or FAILURE; colours match loosely here too |
| `HasCount` | reads the list under `key`, compares its length with `count` | SUCCESS or FAILURE |
| `Place`, `Pour`, `Shake`, `Close` | read their objects through their ports and call `world.place(...)` etc. | from the `Outcome` (`_Action.report()`) |

Find nodes create their blackboard client on their first tick, not when they are built, so
the syntax check's builds register nothing. Every node leaves a `feedback_message`: one
sentence about what it did (`placed white_package_1 in blue_box`, `found only 0 object(s)
with type='cup'`), which the trace shows.

`ForEach` is py_trees' own decorator (`py_trees/decorators.py` in the installed library):
when it starts it reads the list at `source_key`; it writes one item to `target_key`, runs
its child, and moves to the next item on the next tick (returning RUNNING); it succeeds
after the last item and fails as soon as its child fails.

### The executor

`execute(tree_xml, world, max_ticks=None)` in [modules/executor.py](modules/executor.py):

1. **Check.** `xml_tree.check_xml(tree_xml)`. If it fails, return at once with status
   `INVALID` and the errors. A tree that fails the check is never ticked.
2. **Empty the blackboard.** The py_trees blackboard is global, so without
   `Blackboard.clear()` a run would see the previous run's values. The activity stream,
   which records every read and write, is switched on.
3. **Build for this world.** `xml_tree.build_tree(tree_xml, bt_nodes.registry(world))`,
   wrapped in a `py_trees.trees.BehaviourTree` with a `SnapshotVisitor`, which records which
   nodes ran in each tick.
4. **Tick** until the root returns SUCCESS or FAILURE, or until `max_ticks`
   (`EXECUTION_MAX_TICKS`, 200). A node that raises stops the run with status `ERROR` and
   its message; it never crashes the program.
5. **Record every tick** (one trace entry each):
   ```python
   {'tick': 3,
    'visited':    [{'node': 'PlaceUnmarkedObject', 'type': 'Place', 'status': 'SUCCESS',
                    'feedback': 'placed white_package_2 in blue_box'}, …],
    'activity':   [{'key': '/object', 'action': 'READ', 'by': 'PlaceUnmarkedObject',
                    'value': 'white_package_2'}, …],
    'blackboard': {'/bluebox': 'blue_box', '/object': 'white_marked_package_2', …},
    'events':     [{'action': 'Place', 'arguments': {'obj': 'white_package_2',
                    'location': 'blue_box'}, 'action_happened': True,
                    'reason': '', 'fault': ''}]}
   ```
   Names are the short XML names; objects are their ids; the first write to a key is
   shown as `WRITE`; a port read that py_trees logs twice is shown once.
6. **Return** the result:

| Key | Meaning |
|---|---|
| `status` | `SUCCESS`, `FAILURE`, `RUNNING` (not finished at `max_ticks`), `INVALID` (failed the check), `ERROR` (a node raised) |
| `stopped` | `finished`, `max_ticks`, `invalid` or `error` |
| `ticks` | how many ticks ran |
| `trace` | one entry per tick, as above |
| `final_table` | `world.snapshot()`: every object, and every fault |
| `check_errors` | the blocking check messages, for `INVALID` |
| `error` | the message, for `ERROR` |

The result goes through `json.dumps`. `format_trace(result)` turns it into the text
`run_tree.py` prints: per tick the nodes that ran, the blackboard reads and writes, the
world's events and the blackboard afterwards; then the status, where every graspable object
ended up, and the faults.

### `run_tree.py`

The terminal command around `execute()`. It reads the XML, builds a fresh mock world from
the scene, calls `execute()` and prints `format_trace()`.

```bash
python run_tree.py --run data/runs/<run id>             # the run's bt.xml, on the run's scene
python run_tree.py tree.xml --scene scene6              # any XML file, on the scene you name
python run_tree.py --run data/runs/<run id> --step      # pause after every tick (Enter)
python run_tree.py --run data/runs/<run id> --json out.json   # also save the full result
```

- `--run` takes the tree from the run's `bt.xml` and the scene from its `summary.json`. A
  run without an accepted tree has no `bt.xml`; run one of its attempts instead.
- To run a particular attempt, give its `attempts/NN/tree.xml` with `--scene`.
- In a terminal, refusals and faults are printed in red; written to a file or a pipe, the
  text has no colour codes.
- Runs from before the switch to XML have no `tree.xml` and cannot be run.

### The Execution tab

The same executor, in the window. Reopen a run (or finish one), choose an attempt in the
**Attempt** menu, open **Execution**, press **Run tree**. Every press uses a fresh mock world
of the run's scene.

- The button is greyed out, with the reason next to it, when the attempt has no XML tree,
  did not pass the syntax check, or a pipeline run is in progress.
- Choosing another attempt empties the view until **Run tree** is pressed again.
- The whole execution is shown at once, read-only:
  1. a header: attempt number, status, why it stopped, ticks, faults, and the last failure
     (the failed action or check in the last tick of a failed run, or the error);
  2. every tick, under "Tick N": the nodes that ran (SUCCESS green, FAILURE red, RUNNING
     amber, with their feedback), the blackboard reads and writes (writes bold), the
     blackboard after the tick (new keys marked `← new`, changed keys `← changed`), and the
     world's events (`done`; `done, FAULT: …` and `refused — …` in red);
  3. the table at the end: where every graspable object is, what is closed, what holds
     which liquid, and the faults.

The text comes from `execution_lines()` in [gui/execution_text.py](gui/execution_text.py),
which needs no window and is tested on its own.

### A worked example

The scene6 command "place every object either in the palette if they are marked or in the
blue box if not" was accepted by the judge as:

```xml
<FindAll name="FindEveryObject" key="objects"/>
<ForEach name="ForEachObject" source_key="objects" target_key="object">
  <Selector name="ChooseObjectDestination" memory="true">
    <Sequence name="PlaceMarkedObjectInPalette" memory="true">
      <HasProperty name="ObjectIsMarked" obj="{object}" property="marked" value="True"/>
      <FindOne name="FindPalette" key="palette" type="palette"/>
      <Place name="PlaceMarkedObject" obj="{object}" location="{palette}"/>
    </Sequence>
    <Sequence name="PlaceUnmarkedObjectInBlueBox" memory="true">
      <HasProperty name="ObjectIsUnmarked" obj="{object}" property="marked" value="False"/>
      <FindOne name="FindBlueBox" key="bluebox" type="box" color="blue"/>
      <Place name="PlaceUnmarkedObject" obj="{object}" location="{bluebox}"/>
    </Sequence>
  </Selector>
</ForEach>
```

| Tick | What happens | World event |
|---|---|---|
| 1 | `FindEveryObject` has no properties, so it stores all 7 objects: the 5 packages, `brown_palette`, `blue_box`. `ForEach` writes `white_package_1` to `/object`; it is not marked, so the second branch finds the blue box and places it. | `Place(white_package_1, blue_box) done` |
| 2–5 | One package per tick, marked ones on the palette, the others in the box. | 4 × `done` |
| 6 | `ForEach` reaches `brown_palette`. Not marked → second branch → `Place`. Refused → the `Sequence` fails → the `Selector` has no branch left → `ForEach` fails → `Root` fails. | `Place(brown_palette, blue_box) refused — brown_palette is fixed and cannot be grasped` |

Status **FAILURE** after 6 ticks, although every package ended in the right place. With
`graspable="True"` on `FindEveryObject` the list holds only the packages, and the run ends
in **SUCCESS** after 5 ticks. The judge missed this; running the tree shows it.

---

## What a run leaves behind

Every run writes a folder named after its id, and **every attempt keeps its own folder**,
so a repaired tree never overwrites the one it replaces:

```
data/runs/2026-11-05_13-15-22_f873/
├── run.log                  every module together, in order
├── events.jsonl             the same records as JSON, one per line
├── logs/<module>.log        each module on its own
├── summary.json             scene, command, models, efforts, the loop's status, counters,
│                            every attempt with its judgement form, the caps, the times
├── scene.jpg                the scene photo (shown in the window, not sent to the model)
├── scene_objects.txt        the scene's object list (the judge's {scene_objects})
├── scene_knowledge.json     the dictionary the enrichment was given
├── command.txt              what was typed
├── enrichment/              system_prompt.txt · user_message.txt · raw_reply.txt
├── enriched_command.txt
├── attempts/
│   ├── 01/
│   │   ├── generation/          system_prompt.txt · user_message.txt · raw_reply.txt
│   │   ├── tree.xml             the tree the generator wrote
│   │   ├── tester_report.json   every syntax check with its result and line number
│   │   ├── judge_outline.txt    the tree exactly as the judge was shown it
│   │   ├── judge/01/            one folder per judge call
│   │   └── judge_form.json      the judgement form
│   └── 02/ …                    the repair, and its own judgement
├── bt.xml                   the accepted (or baseline) tree, with a comment saying where it came from
├── bt_graph.png             that tree as a picture, with its legend
├── bt_graph.dot             the same graph as DOT source
└── bt_graph.json            the tree structure and the legend's notation lines, to redraw it
```

Files that do not apply are missing: no `enrichment/` when enrichment is off, no `judge/`
in a baseline run, no `bt.xml` when no tree was accepted. Running a tree writes nothing to
the run folder; use `run_tree.py --json` to save a result.

Each attempt in `summary.json` carries a `ground_truth` field, left `null` on purpose. It
is filled in by hand with `"correct"` or `"faulty"`; without it the judge cannot be
evaluated.

Any past run can be reopened from the run menu at the top right of the window, and the
**Attempt** menu switches every tab between that run's attempts.

---

## The graph

No graph library places the nodes. The layout is our own code, computed once (`layout()`
in [modules/graph.py](modules/graph.py)): every box is sized from its text, leaves go left
to right, and each parent is centred over its children. That one layout is then drawn
three ways, so they all show the same picture:

| Output | Drawn with | Where |
|---|---|---|
| the canvas in the window | a tkinter `Canvas` (the buttons around it are customtkinter) | `GraphView` in [gui/graph_view.py](gui/graph_view.py) |
| `bt_graph.png` | Pillow (`ImageDraw`) | `render_png()` in [modules/graph.py](modules/graph.py) |
| `bt_graph.dot` | plain text, written by hand | `to_dot()` in [modules/graph.py](modules/graph.py) |
Every node type has its own colour, and a **legend** under the tree declares them:

| Node | Colour | Symbol | Meaning |
|---|---|---|---|
| Sequence | blue | `→` | runs its children in order and stops at the first failure |
| Selector | orange | `?` | tries its children in order until one succeeds |
| Action | green | — | a robot action: Place, Pour, Shake or Close; the box lists its arguments |
| Find / check | teal | — | `FindOne`, `FindAll`, `HasProperty` or `HasCount`; the class name is under the title |
| Decorator | purple | — | wraps the node under it and changes how it runs or what it returns; the class name is under the title |
| Condition / blackboard | yellow | — | any other py_trees behaviour (not used by the current grammar) |

The legend lists only the node types the tree contains. The colours are `GRAPH_COLORS` in
[config.py](config.py).

**The notation lines.** Under the node types, the legend explains the blackboard notation,
when the tree uses it:

```
{key}      a value read from the blackboard: obj = {object}, source_key = {objects}
plain key  where a find node or ForEach writes: key = objects, target_key = object
           (in the XML, source_key and HasCount's key are written without braces)
```

The `{key}` line appears when an argument is drawn in braces; the plain-key line when a
find node or `ForEach` writes a key. As explained in
[the blackboard section](#the-blackboard-and-the-key-notation), the graph draws a
`ForEach`'s `source_key` and a `HasCount`'s `key` in braces (`READ_KEYS` in
[modules/graph.py](modules/graph.py)). The lines are saved in `bt_graph.json`; an older file
without them is redrawn with the lines worked out from the tree.

The `.dot` file is written always (without the notation lines). When the Graphviz `dot`
program is installed, `render_graphviz()` runs it with `subprocess` to render a
`bt_graph_graphviz.png` as well. Graphviz lays the tree out itself, so that picture can
differ from ours. No Python package is needed for it, only the program:

```bash
brew install graphviz
```

Without it nothing is lost: the PNG and the canvas do not need graphviz.

---

## The prompts

The prompts are in [prompts](prompts). The parts both models read live in their own
files, and the main prompts include them:

```
prompts/
├── bt_generation_prompt.txt     {{include: robot_and_workspace.txt}}
│                                {{include: perception.txt}}
│                                {{include: generic_actions.txt}}
├── semantic_judge_prompt.txt    {{include: robot_and_workspace.txt}}
│                                {{include: perception.txt}}
│                                {scene_objects}
│                                {{include: generic_actions.txt}}
│                                {{include: judge_physical_facts.txt}}
├── robot_and_workspace.txt      the robot and the axes, shared by both prompts
├── perception.txt               what the robot perceives, shared by both prompts
├── generic_actions.txt          the four actions with {key} references, shared by both prompts
├── judge_physical_facts.txt     the facts a tree must respect, for the judge only
└── actions.txt                  the four actions with object ids (from the older,
                                 non-generic trees; not used now)
```

A line `{{include: file.txt}}` is replaced by that file's text when the prompt is loaded
(`load_prompt()` in [modules/prompt_files.py](modules/prompt_files.py)), so the model
receives one continuous prompt. The path is relative to the file that contains the line.
`{scene_objects}` is filled with `str.replace`, never `str.format`, because the prompts
contain braces.

The generator has no physical-facts file on purpose: it only translates, and physical
rules belong to the judge. The generation prompt adds its own sections on the XML format,
the decorators and how to build a tree. The judge prompt explains how to read the tree
outline: how find nodes order objects, `FindOne`'s `nth`, `FindAll`'s `limit`, `HasCount`'s
`comparison`, and what each decorator does.

**The physical facts** ([prompts/judge_physical_facts.txt](prompts/judge_physical_facts.txt)):
a container that holds liquid spills when shaken while open, so it must be closed first;
nothing can be poured into a closed container, so a container is filled before it is
closed; objects that hold or support others are fixed; one cap closes one container. The
mock world applies the same facts: the first as the `spill` fault, the others as refusals.

---

## The scenes

Nine scenes: `scene1`, `scene2_1`, `scene2_2`, `scene3` to `scene8` (`SCENES` in
[config.py](config.py)). [update/SCENES.md](update/SCENES.md) lists every object of every
scene with its id, name, colour, role, liquid and position, every object name with its
perception type, and every liquid.

`load_scene()` in [modules/scene.py](modules/scene.py) reads a scene, normalises the object
and colour names with the contextual-asr CSV files, and gives every object a stable id: the
colour and name (`yellow_bowl`), with a number only when two would collide
(`red_cuboid_1`, `red_cuboid_2`, numbered left to right). Objects whose name is in
`SUPPORT_OBJECTS` get the role `valid location`; the rest are `graspable`.

The scenes, their photos and the enrichment prompts are read from the contextual-asr
project beside this one:

```
Contextual-asr/
├── contextual-asr/contextual-asr/prompt/   ← scenes, photos and enrichment prompts
└── pipeline/                               ← this repository
```

Nothing is duplicated. If you clone this repository on its own, point `CONTEXTUAL_ASR_DIR`
in [config.py](config.py) at that project, or copy `prompt/workspace_knowledge` and the five
enrichment `.txt` files next to it.

---

## The scene photo is not sent to the model

All model stages work from text alone. The photo is still loaded and shown in the window,
and still copied into the run folder; it is simply not part of any request.

The contextual-asr enrichment prompt promises the model a picture in three places, so when
the photo is not sent those sentences are removed from the assembled prompt
(`without_image_references()` in [modules/enrichment.py](modules/enrichment.py)). The
prompt *files* are left untouched, since contextual-asr shares them.

To send it again, set `ENRICHMENT_SEND_SCENE_IMAGE` and `BT_GENERATION_SEND_SCENE_IMAGE`
(and `JUDGE_SEND_SCENE_IMAGE`) back to `True` in [config.py](config.py); the removed
sentences come back with them.

---

## Settings

All in [config.py](config.py). The window's menus override the models, the efforts, the
judge mode and enrichment per run.

| Setting | Default | Meaning |
|---|---|---|
| `CONTEXTUAL_ASR_DIR` and the paths under it | `../contextual-asr/contextual-asr` | where the scenes, the CSVs and the enrichment prompts are read from |
| `BT_GENERATION_PROMPT_FILE`, `SEMANTIC_JUDGE_PROMPT_FILE` | `prompts/…` | the two main prompts |
| `API_KEY_FILE` | `contextual-asr/…/API_KEY.txt` | the key, when `OPENAI_API_KEY` is not set |
| `RUNS_DIR`, `LOG_DIR` | `data/runs`, `data/logs` | where runs and logs are written |
| `SCENES` | the nine scenes | the scene menu |
| `SUPPORT_OBJECTS` | box, crate, bowl, palette, container, mortar, test tube holder, foam test tube holder | objects that hold or support others: never graspable |
| `ENRICHMENT_MODEL`, `BT_GENERATION_MODEL`, `JUDGE_MODEL` | `gpt-4o` | the three models |
| `ENRICHMENT_TEMPERATURE`, `BT_GENERATION_TEMPERATURE`, `JUDGE_TEMPERATURE` | 0 | dropped automatically for a model that refuses it |
| `ENRICHMENT_SEND_SCENE_IMAGE`, `BT_GENERATION_SEND_SCENE_IMAGE`, `JUDGE_SEND_SCENE_IMAGE` | `False` | send the photo with the request |
| `JUDGE_USE_STRUCTURED_OUTPUT` | `True` | ask the judge for the JSON schema |
| `JUDGE_ENABLED` | `True` | Judge (True) or Baseline (False), when the window does not say |
| `GRAMMAR_DECORATORS` | ForEach, Inverter, Retry, Repeat, Timeout, FailureIsSuccess | the decorators the prompt allows and the check accepts |
| `PERCEPTION_TYPES`, `PERCEPTION_COLOR_PROPERTIES`, `PERCEPTION_BOOLEAN_PROPERTIES` | see [the perception properties](#generic-trees-find-and-check-nodes) | must match `prompts/perception.txt` |
| `FIND_POSITIONS` | leftmost, rightmost, nearest, farthest | the `position` values |
| `HAS_COUNT_COMPARISONS` | exactly, at least, at most | the `comparison` values |
| `AVAILABLE_MODELS` | gpt-4o, gpt-4o-mini, gpt-4.1, gpt-4.1-mini, gpt-5, gpt-6-luna | the model menus |
| `RESPONSES_API_MODELS` | `{'gpt-6-luna'}` | models called through the Responses API, with a reasoning effort and no temperature |
| `REASONING_EFFORTS` | low, medium, high | the effort menus |
| `ENRICHMENT_REASONING_EFFORT`, `BT_GENERATION_REASONING_EFFORT`, `JUDGE_REASONING_EFFORT` | medium | the defaults (the enrichment has no menu) |
| `SYNTAX_FAILURE_LIMIT` | 3 | see [the caps](#the-generation-loop-its-caps-and-how-a-run-ends) |
| `JUDGE_REJECTION_LIMIT` | 3 | see the caps |
| `JUDGE_FORMAT_RETRIES` | 2 | see the caps |
| `MOCK_SPILL_FAILS_ACTION` | `False` | whether an action with a fault fails its node (see [Faults](#faults)) |
| `EXECUTION_MAX_TICKS` | 200 | the executor stops a tree that has not finished by then |
| `CONSOLE_LOG_LEVEL`, `FILE_LOG_LEVEL` | INFO, DEBUG | log levels |
| `LOG_BACKUP_COUNT` | 10 | days of global logs kept |
| `GUI_LOG_BUFFER` | 4000 | log records kept for the window's log pane |
| `GRAPH_EXPORT_DOT`, `GRAPH_EXPORT_GRAPHVIZ`, `GRAPH_EXPORT_FORMAT` | `True`, `True`, `png` | write the `.dot`, render it with graphviz when it exists, and in which format |
| `GRAPH_COLORS` | — | the graph's colours, shared by the canvas and the PNG |

A model in `RESPONSES_API_MODELS` takes a reasoning effort and is sent no temperature; its
effort menu is enabled in the window. Any other model keeps using chat completions and never
receives an effort. The effort that was sent is recorded in `summary.json`.

---

## Logging

[core/logging_setup.py](core/logging_setup.py) sets up three kinds of logs:

- **Global**, in `data/logs/`: `debug.log`, `info.log` and `error.log`, rotated at midnight,
  `LOG_BACKUP_COUNT` days kept. `error.log` alone tells you everything that has ever broken.
- **Per run**, in the run folder: `run.log`, `events.jsonl` and `logs/<module>.log`.
- **In the window**: the log pane along the bottom, filterable by module (pipeline, scene,
  command, enrichment, generator, tester, judge, loop, graph, gui) and level.

---

## Tests

```bash
python -m pytest tests -q
```

No test calls a model: the loop is driven with scripted replies. 272 tests:

| File | Tests | What it covers |
|---|---|---|
| [tests/test_loop.py](tests/test_loop.py) | 30 | the real loop with scripted replies and the real syntax check: acceptance, repair after a rejection or a syntax failure, each cap, a reply with no tree, invalid judgement forms, the baseline, one folder per attempt, the judge's earlier judgements, and the form's validation |
| [tests/test_xml_tree.py](tests/test_xml_tree.py) | 57 | reading, checking and building XML trees: every check group, line numbers, the grammar, generic trees |
| [tests/test_graph.py](tests/test_graph.py) | 23 | node kinds, the layout, the legend and its notation lines, braces on read keys, the PNG, DOT and JSON |
| [tests/test_prompt_files.py](tests/test_prompt_files.py) | 11 | includes, and that the prompts and `config.py` agree |
| [tests/test_llm_responses.py](tests/test_llm_responses.py) | 7 | the Responses API path: efforts, no temperature |
| [tests/test_world.py](tests/test_world.py) | 3 | the world interface |
| [tests/test_mock_world.py](tests/test_mock_world.py) | 65 | finding, loose colours, ordering and ties, every action rule, faults, events, every real scene |
| [tests/test_nodes_run.py](tests/test_nodes_run.py) | 38 | every node acting on a world, the registry trap, the spill setting |
| [tests/test_executor.py](tests/test_executor.py) | 27 | whole runs on the real scenes, the trace, stopping, invalid trees, the text output |
| [tests/test_execution_view.py](tests/test_execution_view.py) | 11 | the Execution tab's text |

---

## Requirements

```bash
../contextual-asr/venv/bin/pip install -r requirements.txt
```

| Package | Used for |
|---|---|
| `py_trees>=2.6` | builds and runs the XML tree (2.6 brought the XML parser) |
| `openai>=1.0` | the model calls |
| `customtkinter>=5.2` | the window |
| `pillow>=10.0` | the scene photos and `bt_graph.png` |
| `pytest>=8.0` | the tests |

`py_trees` was the only addition to the contextual-asr environment. The graph's canvas uses
tkinter, which comes with Python, and the optional `bt_graph_graphviz.png` needs only the
Graphviz program (`brew install graphviz`), not a Python package. The mock world and the
executor use nothing beyond py_trees and the standard library.

---

## Branches

Each step of the work is on its own branch, each one built on the one before:

| Branch | What it adds |
|---|---|
| `main` | the first pipeline: command to tree, checked and drawn |
| `BT_Grammar` | the py_trees decorator grammar, enforced by the check |
| `Generalizable-behaviour-tree` | generic trees: find/check nodes, only the judge sees the scene |
| `Generalizable/XML` | the trees are XML, built by the py_trees parser |
| `mock-world` | the world interface, the mock world, `update/SCENES.md` |
| `executor` | the nodes act on a world, the executor, `run_tree.py` |
| `execution-tab` | the Execution tab, the legend's notation, braces on read keys, `action_happened`, done/refused |

---

## Known gaps

- **`ForEach` over an empty list runs its child once.** py_trees ticks the child before it
  checks whether any item is left. If the child reads the loop's target, the run stops with
  `ERROR` (`NoDataAvailable`); if it does not, the child really acts. Fixing it means our own
  `ForEach` class in [modules/bt_nodes.py](modules/bt_nodes.py).
- **`INITIAL_ON` knows only scene8.** Which objects start on others in the other scenes has
  to be read from their photos by hand.
- **No "matching property" relation**, so "the box of the matching colour" gives very large
  trees (see [generic trees](#generic-trees-find-and-check-nodes)).
- **A spilled container keeps its liquid**, and pouring the same colour into a container
  gives that colour, not `mixed`.
- **Running is not part of a pipeline run.** The executor's result is not saved in the run
  folder, and nothing fills `ground_truth` from it.
- **Unity is not connected.** It will be another `World`; the nodes will not change.
