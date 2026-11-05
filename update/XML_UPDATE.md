# Pipeline update: the generator writes XML, py_trees builds it

For the `Generalizable-behaviour-tree` branch (written against commit `cc34ec0`). Read the
whole file before changing code.

**What comes with this spec**

| File | What to do with it |
|---|---|
| `xml_output.patch` | Every change below in one patch. `git apply xml_output.patch` on the branch. |
| `prompts/bt_generation_prompt.txt` | Replaces the generation prompt: the generator now writes XML. |
| `prompts/generic_actions.txt`, `prompts/semantic_judge_prompt.txt` | One sentence each: `@key` becomes `{key}`. |
| `modules/bt_nodes.py` | New. The four actions and the four find/check nodes as py_trees *ports* nodes. |
| `modules/xml_tree.py` | New. Reads, checks and builds an XML tree. |
| `modules/tester.py`, `generator.py`, `loop.py`, `loop_stage.py`, `graph.py`, `gui/app.py`, `config.py`, `requirements.txt`, `README.md` | Changed, as described in section 4. |
| `tests/test_xml_tree.py` | New. Replaces `test_tester.py`, `test_generic_tester.py` and `generic_trees.py`. |
| `tests/test_loop.py`, `tests/test_graph.py`, `tests/test_prompt_files.py` | Changed to XML trees. |

With the patch applied, all 116 tests pass (section 6).

**In scope:** the format the generator writes, the syntax check, building the tree with
py_trees, and the file names a run leaves behind.

**Out of scope, unchanged:** the loop, its caps and final statuses, the judge, the
judgement form, enrichment, the scenes, `summary.json`, and the stand-in status of the
find/check nodes and actions.

---

## 1. Why this change

Today the generator writes a Python function, `create_behavior_tree()`. To check it, the
tester parses it with `ast`, analyses ~1200 lines' worth of rules, and finally **executes
the model's code** in a sandbox to prove it returns a tree.

From now on the generator writes the tree as **data**: an XML document in the
BehaviorTree.CPP format, which py_trees 2.6 reads with its own parser
(`py_trees.parsers.behaviour_tree_xml.parse_behaviour_tree_xml`). That gives:

- **No model-written code is executed.** The parser builds the tree from classes we own.
- **A standard format.** The same `bt.xml` the pipeline accepts is what the executor will
  load later, with the same parser (section 7).
- **Whole classes of error disappear.** Orphaned nodes, a node with two parents, a child
  that was never created, reassigned variables, a missing `return`, a wrong `try/except`:
  none of these can be written in XML, because a child is simply the element inside its
  parent. Eleven checks of the old tester are gone for that reason (section 4.3).
- **The checker is smaller.** The old `tester.py` (1183 lines) becomes a 141-line stage
  plus the 713-line `xml_tree.py`, with no sandbox and no `exec`.

What the tree *means* does not change. It is still generic: find nodes describe objects
by perception properties, store them under keys, and later nodes use them. The four
actions, the four find/check nodes, `Sequence`, `Selector` and the six decorators are
exactly the same grammar.

---

## 2. What the generator writes

```xml
<root main_tree_to_execute="MainTree">
  <BehaviorTree ID="MainTree">
    <Sequence name="Root" memory="true">
      <FindOne name="FindRack" key="rack" type="box" color="blue"/>
      <FindAll name="FindFlasks" key="flasks" type="measuring cylinder"/>
      <ForEach name="ForEachFlask" source_key="flasks" target_key="flask">
        <Place name="PlaceFlask" obj="{flask}" location="{rack}"/>
      </ForEach>
    </Sequence>
  </BehaviorTree>
</root>
```

| Python (before) | XML (now) |
|---|---|
| `def create_behavior_tree():` with `try/except` and `return root` | `<root main_tree_to_execute="MainTree">` holding `<BehaviorTree ID="MainTree">` |
| `root = py_trees.composites.Sequence(name="Root", memory=True)` | `<Sequence name="Root" memory="true">` |
| `root.add_children([find_1, for_1])` | the children written inside, in order |
| `ForEach(name=…, child=place_1, source_key=…, target_key=…)` | `<ForEach name=… source_key=… target_key=…>` with the child inside |
| `obj="@flask"` | `obj="{flask}"` |
| `key="rack"`, `source_key="flasks"`, `HasCount(key="flasks")` | unchanged: plain names |
| `times=2`, `graspable=True` | `times="2"`, `graspable="True"` (every value is quoted) |
| variables `find_1`, `place_1`, … | none |

The one notation change is **`@key` → `{key}`**. Curly braces are what py_trees itself uses
for "this blackboard entry", so the parser wires the reference for us (section 3).

---

## 3. How py_trees reads it (tested against py_trees 2.6.0)

Everything here was tested with the installed py_trees 2.6.0, not taken from the docs.

**What the parser does for us**

- It builds `Sequence` and `Selector` (attributes `name`, `memory`) and **every
  py_trees decorator by its tag name**: `ForEach`, `Inverter`, `Retry`, `Repeat`,
  `Timeout`, `FailureIsSuccess`. The decorator's attributes become its constructor
  arguments, converted to the annotated types (`num_failures="2"` → `2`).
  *The docs page "Ports (Experimental)" still says built-in decorators are not supported
  in XML. The 2.6.0 code does support them, and the tests here depend on it. Keep
  py_trees at 2.6 or later.*
- It only builds leaves that are `PortsMixin` classes, so our eight leaves are ports nodes
  (`modules/bt_nodes.py`). For every attribute:
  - if it is a declared **port** (`obj`, `location`, `source`, `target`, `closing_obj`),
    `{flask}` is wired to the blackboard key `/flask`;
  - otherwise it is a **constructor argument**, converted to the annotated type
    (`times: int`, `graspable: bool | None`, …). Braces there are refused.
- The keys line up. A `ForEach` with `target_key="flask"` writes `/flask`, a find node with
  `key="rack"` stores `/rack` (once it has its real `update()`, section 7), and a port
  written `{flask}` reads `/flask`. This was ticked end to end with test versions of the
  find nodes on a fake table: a `FindAll` → `ForEach` → `Place` tree placed each found
  object.
- We pass the parser an explicit `node_registry` (`bt_nodes.REGISTRY`), so it builds
  none of the other ports classes that may be registered.

**What the parser does *not* do, so `xml_tree.py` checks it first**

| Written | What the parser does | Caught by |
|---|---|---|
| `<Place … obj="{cube}"/>` without `location` | builds it; fails only when ticked | `arguments.signatures` |
| `obj="{nothing}"` (no node stores it) | builds it; fails only when ticked | `objects.references` |
| `times="two"` | builds it with the string `"two"` | `arguments.counts` |
| `<OneShot>` or any other py_trees decorator | builds it | `structure.allowed_nodes` |
| `memory` missing or misspelled (`memroy`) | silently uses `true` | `structure.memory_written` (warning) |
| `memory="yes"` | silently uses `false` | `structure.memory` |
| the same name under two different parents | builds it | `structure.unique_names` |
| any error | a message with no line number | every check carries its line |

Two more things the parser does:
- It **prefixes every node name** with its parents' names (`Root.ForEachFlask.PlaceFlask`).
  `xml_tree.py` renames the built nodes back to the XML names, which the checks keep
  unique, so the graph, the judge outline and the logs show the names the generator wrote.
- It reads **a file path**, not a string, so the tree is written to a temporary file first.

---

## 4. Changes, file by file

### 4.1 Prompts

`prompts/bt_generation_prompt.txt` is rewritten for XML. What changed:
- A new section, **Writing a tree in XML**: a node is an element, arguments are quoted
  attributes, children are written inside, and the document frame
  (`<root>`/`<BehaviorTree ID="MainTree">`/`<Sequence name="Root" memory="true">`).
- **The blackboard**: object arguments are `{key}`; braces appear nowhere else.
- Every example is now XML: `position="leftmost" nth="2"`, the `ForEach` nesting, the
  `Inverter` around a condition.
- **Building the tree** loses the Python-only rules (variables, `add_children`, "create a
  decorator's child before the decorator", "a node can have only one parent"). It gains
  "names are letters and digits only", because the parser joins names with dots.
- **Code format** becomes **XML format**: only the tags in the prompt, no `SubTree`,
  `Include` or `Parallel`; comments allowed.
- **Output**: exactly one ```` ```xml ```` block with the whole `<root>` document.

These are unchanged, word for word where possible: the generic-tree principle, "translate,
don't check", the property rules, *Where to find objects*, all three kinds of *Choices,
fallbacks and failures*, and *Follow-up messages*. No physical rules were added.

`prompts/generic_actions.txt`, which both prompts include: "is an @ reference to an
object that a find node stored earlier" becomes "is a {key} reference to an object that a
find node or a ForEach stored earlier".

`prompts/semantic_judge_prompt.txt`: the one bullet `An argument written "@key"` becomes
`An argument written "{key}"`. Nothing else changes. The judge still reads the same
outline, `Type(arguments) [Name]`, built from the tree.

Placeholders are still filled with `str.replace`, never `str.format`: the prompts now
contain literal `{key}` references.

### 4.2 `modules/bt_nodes.py` (new)

The eight leaves as `py_trees.ports.BehaviourWithPorts` classes, plus `REGISTRY`, the
`{tag: class}` dict handed to the parser.
- Actions declare their object arguments as input ports. `Shake` takes `times: int`. The
  class attribute `action` lets `graph.py` draw them as actions.
- `FindOne` and `FindAll` take `key` and the perception properties as annotated
  constructor arguments. The property names must match `config.PERCEPTION_*`, which a
  test enforces.
- `HasProperty` takes `obj` as a port and `property`/`value` as constructor arguments.
  `HasCount` takes `key`, `count: int` and `comparison`.
- Find/check nodes have `perception = True`, so `graph.py` colours them as before.
- Every node has an `arguments` dict, filled after the build, for the graph and the judge
  outline.

They are **stand-ins**, as before: `update()` returns SUCCESS. The executor replaces the
`update()` bodies and keeps the constructors and ports, because the XML is written
against them (section 7).

### 4.3 `modules/xml_tree.py` (new) and `modules/tester.py`

`xml_tree.py` holds:
- `extract_xml(answer)`: the ```` ```xml ```` block, any fenced block holding `<root`, or
  a bare `<root>…</root>`.
- `read_xml(text)`: an expat reader that keeps each element's line number (ElementTree
  does not).
- The grammar tables `LEAVES`, `COMPOSITES` and `DECORATORS`; `grammar()` filters the
  decorators by `config.GRAMMAR_DECORATORS`.
- `check_xml(text) -> (checks, built_tree, root_element)`: the checks, then the build.
- `_build()`: the temporary file, `parse_behaviour_tree_xml(…, node_registry=REGISTRY)`,
  then renaming and labelling the built nodes.

The check ids stay where the meaning stayed:

| | Check ids |
|---|---|
| **Kept** | `syntax.parse`, `structure.root_type`, `structure.allowed_nodes`, `structure.memory`, `structure.unique_names`, `structure.name_style`, `structure.inverter`, `arguments.signatures`, `arguments.counts`, `arguments.names`, `objects.properties`, `objects.keys`, `objects.references`, `build.node_count` |
| **New** | `syntax.document` (the frame), `syntax.text` (stray text, warning), `structure.memory_written` (missing `memory`, warning), `structure.children` (composites have children, decorators exactly one, leaves none), `build.parse` (the py_trees parser builds it) |
| **Gone**: XML cannot express the mistake (the three `build.*` ones are replaced by `build.parse`) | `syntax.function`, `syntax.signature`, `syntax.only_function`, `structure.try`, `structure.handler`, `structure.return`, `structure.unique_variables`, `structure.reachable`, `structure.single_parent`, `structure.known_children`, `structure.one_root_call`, `build.exec`, `build.call`, `build.type` |

`build.parse` runs only when no error check failed before it. Otherwise it is reported as
a skipped warning, so the generator is not sent the same problem twice in the parser's
less precise words.

`tester.py` keeps `SyntaxTestStage` with `check()`, `passed()`, `execute()`, `_report()` and
`_as_text()`. `check()` now returns `xml_tree.check_xml(...)`. Removed: the `ast`
analysis, the sandbox and its recording py_trees wrappers, `_error_behind_try`, and
`spill_label`. `spill_label` already returned `None` for every generic tree.

### 4.4 `modules/generator.py`

- `extract_code()` keeps its name and returns `xml_tree.extract_xml(answer)`, so the loop
  and its tests need no change.
- `as_module()` is replaced by `as_document()`: the accepted XML with a comment header
  (scene, command, enriched command, model). `--` is escaped, because XML comments may not
  contain it.

### 4.5 `modules/loop.py`

Only `NO_CODE_PROBLEM` changes: "Your reply contained no ```xml block with the tree.
Return the tree." Two docstrings follow. Everything else stays as it is: the messages,
the judge history, the caps, the statuses, `outline_for_judge`.

### 4.6 `modules/loop_stage.py`

- Each attempt writes `attempts/NN/tree.xml` instead of `create_behavior_tree.py`.
- The accepted tree is written as `bt.xml` (with `as_document`), instead of `bt.py` and
  `create_behavior_tree.py`.
- `analysis_labels.json` is no longer written (see `spill_label` above).

```
data/runs/<run id>/
├── attempts/01/
│   ├── generation/            system_prompt.txt · user_message.txt · raw_reply.txt
│   ├── tree.xml               (was create_behavior_tree.py)
│   ├── tester_report.json
│   ├── judge_outline.txt
│   ├── judge/01/ …
│   └── judge_form.json
├── bt.xml                     (was bt.py and create_behavior_tree.py)
└── … bt_graph.png/.dot/.json, summary.json as before
```

### 4.7 `gui/app.py`, `modules/graph.py`

- `gui/app.py`: the *Code* tab is renamed *XML*. A stored attempt is read from
  `tree.xml`, and the no-tree message says "no ```xml block with the tree".
- `graph.py`: a comment only. It already tells node kinds apart by `action`,
  `perception` and the py_trees decorator class, which the new nodes keep.

### 4.8 `config.py`, `requirements.txt`, `README.md`

- `config.py`: `GRAMMAR_BEHAVIOURS` and `GRAMMAR_HELPERS` are removed (nothing reads them
  now). The comment on `GRAMMAR_DECORATORS` points at `xml_tree.py`.
- `requirements.txt`: `py_trees>=2.6`.
- `README.md`: the overview, the module table, a new section *The trees are XML, built by
  py_trees*, the generic-trees example, the feedback example, the syntax-check table and
  the run folder.

### 4.9 Tests

- Removed: `tests/test_tester.py`, `tests/test_generic_tester.py`,
  `tests/generic_trees.py` (Python trees).
- Added: `tests/test_xml_tree.py`, 57 tests: the reference trees in XML, the judge
  outline, every check's failure cases, the build, `bt_nodes` against the config and the
  grammar.
- `test_loop.py`: the scripted replies are XML trees; the ten loop cases are unchanged.
- `test_graph.py`: the fixture tree is built from XML; one py_trees behaviour is added by
  hand, so the graph's "behaviour" drawing path stays tested.
- `test_prompt_files.py`: a new test checks that the generation prompt asks for XML, has
  no `@` and names every decorator of `GRAMMAR_DECORATORS`.

---

## 5. Step by step

1. **Install py_trees 2.6 in the contextual-asr environment**
   ```bash
   ../contextual-asr/venv/bin/pip install "py_trees>=2.6"
   ../contextual-asr/venv/bin/python -c "import importlib.metadata as m; print(m.version('py_trees'))"
   ```
   It must print 2.6.0 or later. The XML parser and the decorators in XML need it.
2. **Make a branch** from `Generalizable-behaviour-tree`, for example `xml-trees`.
3. **Apply the patch**
   ```bash
   git apply --check xml_output.patch && git apply xml_output.patch
   ```
   The patch also deletes `tests/test_tester.py`, `tests/test_generic_tester.py` and
   `tests/generic_trees.py`. Without the patch: copy the files of this folder over the
   repo and delete those three yourself.
4. **Run the tests**
   ```bash
   ../contextual-asr/venv/bin/python -m pytest tests -q
   ```
   Expect 116 passed. The loop tests need the real `scene8` from contextual-asr.
5. **Open the window and run one command by hand**, judge on, enrichment off (as for
   every generic run). Check that the *XML* tab shows the tree, the *Checks* tab lists the
   new checks, the graph is drawn, and `data/runs/<id>/` holds `attempts/01/tree.xml` and
   `bt.xml`.
6. **Run the live smoke tests** in section 8 and keep their run folders.
7. **Commit**, and note the switch in the study log (section 8: runs before and after are
   different conditions).

---

## 6. Tests

With the patch applied: **116 passed**. That is the 118 tests of the branch, minus the 60
in the two removed Python-tree test files, plus the 57 in `test_xml_tree.py` and one new
prompt test.

The ten loop cases now drive the real pipeline with XML replies:
- a rejected tree is repaired;
- an unknown `{flask}` comes back to the generator as `no node stores "flask"` under
  `SYNTAX CHECK ERRORS:`;
- every cap and the baseline behave as before;
- every attempt keeps its own `tree.xml`.

`test_xml_tree.py` also checks:
- that a built tree carries the XML names and typed arguments, and that
  `loop.outline_for_judge` reads it;
- that `bt_nodes` takes exactly the perception properties in the config;
- that a tree without a loop ticks to SUCCESS with the stand-ins.

---

## 7. Running a tree later (the executor)

The accepted `bt.xml` is loaded and run like this. Loading was tested, including the
comment header:

```python
import py_trees
from py_trees.parsers.behaviour_tree_xml import parse_behaviour_tree_xml
from modules import bt_nodes

root = parse_behaviour_tree_xml('data/runs/<run id>/bt.xml', node_registry=bt_nodes.REGISTRY)
tree = py_trees.trees.BehaviourTree(root)
tree.tick_tock(period_ms=100, stop_on_terminal_state=True)
```

With today's stand-ins, a tree with a `ForEach` cannot be ticked yet: the stand-in
`FindAll` stores nothing, so `ForEach` finds no list under its `source_key`. That is
expected. The executor gives the leaves their real `update()`. This pattern was tested
end to end on a fake table, where `ForEach` looped over the found objects and `Place`
received each one:

```python
class FindAll(_Find):
    def __init__(self, name, key, **kwargs):
        super().__init__(name=name, key=key, **kwargs)
        self.store = py_trees.blackboard.Client(name=name)
        self.store.register_key(key=key, access=py_trees.common.Access.WRITE)

    def update(self):
        self.store.set(self.key, perceive(self.properties, self.position, self.limit))
        return py_trees.common.Status.SUCCESS

class Place(_Action):
    def update(self):
        obj, location = self.get_input('obj'), self.get_input('location')   # the ports
        ...   # move the robot
```

`HasCount` reads its list the same way, with `Access.READ`. A plain key `"rack"` and a
port `{rack}` both resolve to `/rack`.

---

## 8. Open points

- **Not run with a real model.** These were tested with scripted replies only. Run a few
  live commands (enrichment off) and keep the run folders, for example:
  1. "Shake the test tube two times." Expected: the tree has no Close, the judge rejects
     it, and the repair adds a find for the cap and a Close before the Shake.
  2. "Put every marked package on the palette." Expected: FindAll, ForEach, Place.
  3. "If the cube is red put it in the box, otherwise in the bowl." Expected: a choice
     with an Inverter branch.

  Watch the syntax-failure rate on the first attempt. If the model often breaks the
  frame or forgets the braces, that shows up in `tester_report.json`.
- **The window was not opened here.** `gui/app.py` compiles, but customtkinter was not
  installed where this was tested. Step 5 checks it.
- **Failed attempts have no graph.** The tree is only built when the checks pass. The old
  sandbox sometimes built trees with failed checks.
- **Pin the version for the study.** The XML parser is marked experimental in py_trees.
  For the duration of the study, consider `py_trees==2.6.0` instead of `>=2.6`.
- **Study comparability.** The output format is part of the generator condition. Do not
  pool runs made with Python trees and runs made with XML trees. Record the switch
  (date, commit) and compare within one format.
- **The main (id-based) branch** could switch the same way. Its object arguments would be
  constant ids (`obj="red_cuboid_1"`) instead of `{key}` references, and it would need its
  own prompt and checks. Not done here.

---

## 9. Do not

- Do not let the parser build anything outside `bt_nodes.REGISTRY` (never pass `"auto"`).
- Do not hand a document to the parser before `xml_tree.py`'s checks pass: the parser
  accepts things the prompt forbids.
- Do not use `{…}` anywhere except object references, and do not write object ids in a
  generic tree.
- Do not add physical rules or a self-check list to the generation prompt (unchanged from
  `PIPELINE_UPDATE.md`).
- Do not implement the real find/check nodes or actions in this step. They stay stand-ins
  until the executor exists.
- Do not fill prompts with `str.format`.
