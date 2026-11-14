# Static creator

Mode id `static_creator`. Defined in `modules/modes.py`.

## 1. What this mode is

The creator writes a tree from the command alone, and nothing judges it. A tree that
fails the syntax check is sent back for repair; the first tree that passes it is the
result. This is the starting point the other two modes are compared against:

- against **Static creator & Dynamic judge** it differs only in the judge: the creator
  prompt is the same file, word for word, and so is the loop;
- against **Dynamic creator** it differs only in what the creator is given: neither has a
  judge, and both use the same loop.

## 2. What the creator sees

The system prompt is `modes/static_creator/creator_prompt.txt`, assembled by
`modules/prompt_files.py: load_prompt()` (each `{{include: …}}` line is replaced by its
file). In order:

| Part | From |
|---|---|
| The role: write a behavior tree in XML from one command, never ask questions | `creator_prompt.txt` |
| The tree is generic: "You are not told which objects are on the table", and it never names an object | `creator_prompt.txt` |
| The job: translate the command faithfully, not check it; "A separate reviewer checks every tree…" | `creator_prompt.txt` |
| Robot and workspace | `prompts/shared/robot_and_workspace.txt` |
| What the robot perceives (types, colours, the True/False properties) | `prompts/shared/perception.txt` |
| Writing a tree in XML · The blackboard · Finding and checking objects | `creator_prompt.txt` |
| Actions (Place, Pour, Shake, Close with `{key}` arguments) | `prompts/shared/generic_actions.txt` |
| Decorators · Describing the objects the command needs · Where to find objects · Building the tree · Choices, fallbacks and failures · XML format · Follow-up messages · Output | `creator_prompt.txt` |

- **The scene object list: no.** The prompt has no `{scene_objects}` placeholder, and
  `BTGenerator.system_prompt()` raises a `StageError` if it ever had one in this mode.
- **The physical facts: no.** `prompts/shared/physical_facts.txt` is not included.
- The scene photo is not sent (`config.BT_GENERATION_SEND_SCENE_IMAGE = False`).

The prompt still says a separate reviewer checks every tree. That sentence is kept on
purpose: the prompt is the same file as the Static creator & Dynamic judge's, so that the
two modes differ only in whether a judge is called.

## 3. What the judge sees

This mode has no judge.

## 4. The first message

From run `data/runs/static_creator/2026-11-14_12-17-43_bda3` (scene8),
`attempts/01/generation/user_message.txt`:

```
COMMAND: shake the test tube 3 times
```

That is the whole message. It is built by `modules/loop.py: generator_message()`. The
command goes in exactly as typed.

The tree that came back (`attempts/01/tree.xml`):

```xml
<root main_tree_to_execute="MainTree">
  <BehaviorTree ID="MainTree">
    <Sequence name="Root" memory="true">
      <FindOne name="FindTestTube" key="tube" type="test tube"/>
      <Shake name="ShakeTube" obj="{tube}" times="3"/>
    </Sequence>
  </BehaviorTree>
</root>
```

It passed the syntax check and was the result (`no_judge`). On the mock world it ends in
SUCCESS with one fault, `spill`, because the open tube is shaken. Nothing in this mode
could have caught that.

## 5. What comes back on a repair

Only syntax problems come back, through `generator_message(command, previous_code,
problems)` with `problems` from `syntax_problems()`. None of the test runs needed a
repair, so this example was produced by the pipeline's own functions (the scripted
broken tree of `tests/test_loop.py`, `TREE_WITH_UNKNOWN_KEY`):

```
COMMAND: shake the test tube 3 times
PREVIOUS TREE:
<root main_tree_to_execute="MainTree">
  <BehaviorTree ID="MainTree">
    <Sequence name="Root" memory="true">
      <FindOne name="FindTube" key="tube" type="test tube"/>
      <FindOne name="FindCap" key="cap" type="test tube cap"/>
      <Shake name="ShakeTube" obj="{flask}" times="2"/>
    </Sequence>
  </BehaviorTree>
</root>
SYNTAX CHECK ERRORS:
- Every object is a {key} stored before it is used: line 6: obj="{flask}": no node stores "flask"
```

A reply with no ```` ```xml ```` block gets this instead (`loop.NO_CODE_PROBLEM`), with
no previous tree:

```
COMMAND: shake the test tube 3 times
Your reply contained no ```xml block with the tree. Return the tree.
```

## 6. How a run ends

One cap applies: `config.SYNTAX_FAILURE_LIMIT = 3`. A reply with no code counts as a
syntax failure. The judge's caps (`JUDGE_REJECTION_LIMIT`, `JUDGE_FORMAT_RETRIES`) never
come into play.

| Final status | When |
|---|---|
| `no_judge` | a tree passed the syntax check; it is the result, not judged |
| `failed_syntax_cap` | the 3rd tree (or reply without code) failed the syntax check |
| `error` | the run stopped with an error |

## 7. Where its runs are

`data/runs/static_creator/<run id>/`. The folder's `README.txt` points back here. In a
run folder:

| File | What it is |
|---|---|
| `summary.json` | the whole run; `mode` and `loop.mode` say `static_creator`, `loop.models.judge` is `null`, `loop.attempts` has one entry per attempt |
| `bt.xml` | the resulting tree, with a header comment (scene, mode, command, model) |
| `bt_graph.png`, `bt_graph.json`, `bt_graph.dot` | the drawn tree |
| `scene_objects.txt`, `scene.jpg` | the scene, for the person reading the run (the creator saw neither) |
| `command.txt` | the command as typed |
| `run.log`, `events.jsonl`, `logs/` | the logs |

An attempt folder `attempts/NN/`:

| File | What it is |
|---|---|
| `generation/system_prompt.txt` | the exact system prompt sent |
| `generation/user_message.txt` | the exact user message sent |
| `generation/raw_reply.txt` | the model's reply |
| `tree.xml` | the XML taken from the reply |
| `tester_report.json` | the syntax check: passed, and every check |

There is no `judge/`, `judge_outline.txt` or `judge_form.json` in this mode.

## 8. The files in this folder

- `README.md`: this description.
- `creator_prompt.txt`: the creator's system prompt. Static creator & Dynamic judge uses
  it too, through an include.
