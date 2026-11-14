# Static creator & Dynamic judge

Mode id `static_creator_dynamic_judge`. Defined in `modules/modes.py`. The default
mode (`config.DEFAULT_MODE`).

## 1. What this mode is

The creator writes a tree from the command alone, exactly as in the Static creator mode.
A semantic judge, which does see the scene and the physical facts, then reads every tree
that passes the syntax check and accepts or rejects it. A rejected tree goes back to the
creator with the judge's findings, up to three rejections. It is compared against:

- **Static creator**: the same creator prompt word for word and the same loop. The
  only difference is that this mode calls the judge;
- **Dynamic creator**: there the knowledge the judge has here (the scene and the
  physical facts) is given to the creator instead, and there is no judge. These two
  modes differ in two things at once, where the knowledge sits and how many tries there
  are (see `modes/README.md`).

Runs made before the modes existed with the judge on are listed as this mode with
"(old run)". Many of them rewrote the command first with the enrichment stage, which no
longer exists, so they are not exactly this mode.

## 2. What the creator sees

The system prompt is `modes/static_creator_dynamic_judge/creator_prompt.txt`, which holds
one line:

```
{{include: ../static_creator/creator_prompt.txt}}
```

So the creator sees exactly what the Static creator sees, and the two can never drift
apart (`tests/test_prompt_files.py` and `tests/test_modes.py` check that the assembled
prompts are identical). Its parts, in order:

| Part | From |
|---|---|
| The role: write a behavior tree in XML from one command, never ask questions | `modes/static_creator/creator_prompt.txt` |
| The tree is generic: "You are not told which objects are on the table" | same |
| The job: translate the command faithfully, not check it; "A separate reviewer checks every tree…" | same |
| Robot and workspace | `prompts/shared/robot_and_workspace.txt` |
| What the robot perceives | `prompts/shared/perception.txt` |
| Writing a tree in XML · The blackboard · Finding and checking objects | `modes/static_creator/creator_prompt.txt` |
| Actions | `prompts/shared/generic_actions.txt` |
| Decorators · Describing the objects the command needs · Where to find objects · Building the tree · Choices, fallbacks and failures · XML format · Follow-up messages · Output | `modes/static_creator/creator_prompt.txt` |

- **The scene object list: no.**
- **The physical facts: no.**
- No scene photo (`config.BT_GENERATION_SEND_SCENE_IMAGE = False`).

## 3. What the judge sees

The system prompt is `modes/static_creator_dynamic_judge/judge_prompt.txt`, filled by
`modules/judge.py: SemanticJudge.system_prompt()`. In order:

| Part | From |
|---|---|
| The role: review a tree before it is executed, answer with a judgement form | `judge_prompt.txt` |
| The tree is generic, and "Its author was not shown the table. You are shown the table" | `judge_prompt.txt` |
| When to accept, and that the reason goes back to the author | `judge_prompt.txt` |
| Input: COMMAND, EARLIER JUDGEMENTS (if present), BEHAVIOR TREE | `judge_prompt.txt` |
| Robot and workspace | `prompts/shared/robot_and_workspace.txt` |
| What the robot perceives | `prompts/shared/perception.txt` |
| Scene: the object list of this scene, one line per object (`{scene_objects}`) | `judge_prompt.txt` + `modules/scene.py: Scene.objects_block()` |
| Actions | `prompts/shared/generic_actions.txt` |
| Physical facts | `prompts/shared/physical_facts.txt` |
| How to read the tree · How to judge · Answer (the form) | `judge_prompt.txt` |

- **The scene object list: yes.** For scene8:

  ```
  - white_foam_test_tube_holder: foam test tube holder, white, valid location, position x=0.624 y=0.000 z=0.024
  - transparent_test_tube_1: test tube, transparent, contains transparent red liquid (67% full), graspable, position x=0.427 y=0.244 z=0.086
  - transparent_test_tube_2: test tube, transparent, contains transparent red liquid (67% full), graspable, position x=0.427 y=0.271 z=0.086
  - transparent_test_tube_3: test tube, transparent, contains transparent red liquid (67% full), graspable, position x=0.427 y=0.299 z=0.086
  - yellow_test_tube_cap_1: test tube cap, yellow, graspable, position x=0.508 y=0.378 z=0.015
  - yellow_test_tube_cap_2: test tube cap, yellow, graspable, position x=0.552 y=0.378 z=0.015
  - yellow_test_tube_cap_3: test tube cap, yellow, graspable, position x=0.598 y=0.378 z=0.015
  - grey_test_tube_holder: test tube holder, grey, valid location, position x=0.427 y=0.272 z=0.045
  ```
- **The physical facts: yes.**
- It does not see the XML. It sees an outline of the built tree
  (`modules/loop.py: outline_for_judge()`), with every node's type and arguments.
- No scene photo (`config.JUDGE_SEND_SCENE_IMAGE = False`).
- The answer is a JSON form, `analysis`, `verdict`, `errors`, `reason`, requested as
  structured output (`config.JUDGE_USE_STRUCTURED_OUTPUT`) and always validated by
  `loop.parse_judgement()`.

## 4. The first message

From run `data/runs/static_creator_dynamic_judge/2026-11-14_12-17-47_ddb0` (scene8).

The creator's message, `attempts/01/generation/user_message.txt`:

```
COMMAND: shake the test tube 3 times
```

The tree it wrote found a test tube and shook it, with no cap. The judge's message,
`attempts/01/judge/01/user_message.txt` (built by `loop.judge_message()`):

```
COMMAND: shake the test tube 3 times
BEHAVIOR TREE:
Sequence [Root]
    FindOne(key="tube", type="test tube") [FindTestTube]
    Shake(obj="{tube}", times=3) [ShakeTube]
```

Its form, `attempts/01/judge_form.json`:

```json
{
  "analysis": "1. Find the test tube: Passes, as there are test tubes on the table. 2. Shake the test tube: Fails, as the test tube is not closed and will spill liquid.",
  "verdict": "reject",
  "errors": ["Test tube is not closed before shaking"],
  "reason": "The Shake node [ShakeTube] attempts to shake a test tube that contains liquid without closing it first, which will cause the liquid to spill."
}
```

## 5. What comes back on a repair

**After a rejection.** From the same run, `attempts/02/generation/user_message.txt`
(`generator_message()` with `reviewer_problems(form)`). The errors and the reason go
back; the analysis does not:

```
COMMAND: shake the test tube 3 times
PREVIOUS TREE:
<root main_tree_to_execute="MainTree">
  <BehaviorTree ID="MainTree">
    <Sequence name="Root" memory="true">
      <FindOne name="FindTestTube" key="tube" type="test tube"/>
      <Shake name="ShakeTube" obj="{tube}" times="3"/>
    </Sequence>
  </BehaviorTree>
</root>
REVIEWER FINDINGS:
Problems: Test tube is not closed before shaking.
Reason: The Shake node [ShakeTube] attempts to shake a test tube that contains liquid without closing it first, which will cause the liquid to spill.
```

The judge then sees the new tree with its own earlier judgement,
`attempts/02/judge/01/user_message.txt`:

```
COMMAND: shake the test tube 3 times
EARLIER JUDGEMENTS:
Attempt 1
Tree:
Sequence [Root]
    FindOne(key="tube", type="test tube") [FindTestTube]
    Shake(obj="{tube}", times=3) [ShakeTube]
Verdict: reject
Errors: Test tube is not closed before shaking
Reason: The Shake node [ShakeTube] attempts to shake a test tube that contains liquid without closing it first, which will cause the liquid to spill.

BEHAVIOR TREE:
Sequence [Root]
    FindOne(key="tube", type="test tube") [FindTestTube]
    FindOne(key="cap", type="test tube cap") [FindTestTubeCap]
    Close(obj="{tube}", closing_obj="{cap}") [CloseTestTube]
    Shake(obj="{tube}", times=3) [ShakeTube]
```

It accepted this tree. On the mock world it ends in SUCCESS with no fault.

**After a syntax failure.** The same message as in the Static creator mode: `PREVIOUS
TREE:` followed by `SYNTAX CHECK ERRORS:` (see `modes/static_creator/README.md`,
section 5). A tree that fails the syntax check is never shown to the judge, and is not
part of its earlier judgements.

**After a form the judge got wrong.** The judge is asked again with its message
followed by `Your previous answer was not a valid judgement form: <why>. Answer with
only the JSON object.`

## 6. How a run ends

| Cap | Value | Counts |
|---|---|---|
| `config.SYNTAX_FAILURE_LIMIT` | 3 | trees (and replies with no code) that failed the syntax check |
| `config.JUDGE_REJECTION_LIMIT` | 3 | trees the judge rejected; syntax failures do not count |
| `config.JUDGE_FORMAT_RETRIES` | 2 | extra judge calls when a reply is not a valid form |

| Final status | When |
|---|---|
| `accepted` | the judge accepted a tree; it is the result |
| `failed_judge_cap` | the 3rd tree was rejected |
| `failed_syntax_cap` | the 3rd syntax failure |
| `judge_error` | the judge gave no valid form in 1 + 2 calls; the tree is never accepted |
| `error` | the run stopped with an error |

## 7. Where its runs are

`data/runs/static_creator_dynamic_judge/<run id>/`. The run folder holds the same files
as a Static creator run (`summary.json`, `bt.xml`, the graph, `scene_objects.txt`,
`scene.jpg`, `command.txt`, the logs). In `summary.json`, `mode` and `loop.mode` say this
mode, and `loop.models.judge` describes the judge, with its prompt file. Its old runs are
directly in `data/runs/<run id>/`.

An attempt folder `attempts/NN/`:

| File | What it is |
|---|---|
| `generation/system_prompt.txt`, `user_message.txt`, `raw_reply.txt` | the creator call |
| `tree.xml` | the XML taken from the reply |
| `tester_report.json` | the syntax check |
| `judge_outline.txt` | the outline the judge was shown (only if the syntax check passed) |
| `judge/01/…`, `judge/02/…` | each judge call: `system_prompt.txt`, `user_message.txt`, `raw_reply.txt` |
| `judge_form.json` | the valid form, analysis included |

## 8. The files in this folder

- `README.md`: this description.
- `creator_prompt.txt`: one include line, the Static creator's prompt.
- `judge_prompt.txt`: the judge's system prompt.
