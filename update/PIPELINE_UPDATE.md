# Pipeline update: LLM semantic judge, generator without validation

This is the next step for the behavior tree pipeline in this repository. Read the whole
file before changing code.

**Files that come with this spec**

| File | What to do with it |
|---|---|
| `prompts/bt_generation_prompt.txt` | Replaces the current generation prompt. |
| `prompts/semantic_judge_prompt.txt` | New. The prompt of the semantic judge. |
| `reference_loop.py` | Tested reference code: judgement form, message formats, and the loop with its caps. Adapt it to `core.pipeline`; keep its behaviour. |

**In scope:** a new semantic judge stage (an LLM), a generator that only generates,
repair loops, logging.

**Still out of scope:** planner, simulation, execution, a human judge, ASR input.

**The system is fully autonomous.** No human is ever asked anything. The BT creator
always builds a tree, and the judge is the only one who decides whether it is right.

---

## 1. Why this change

The current pipeline runs Scene → Command → Enrichment → Generator → Syntax check →
Graph. It was built without a judge on purpose, and that part is correct.

The problem is the generation prompt. Besides generating, it also validated the plan
(ordering rules, the close-before-shake rule, a final checklist) and clarified unclear
commands (Rule U, Rule A). Together these covered every category of the judgement form,
so a faulty tree could never reach a judge: the generator either declined or produced a
correct tree.

From now on each part has one job:

| Part | Does | Does not |
|---|---|---|
| Enrichment (unchanged) | Maps the user's words to the names of the objects in the scene, for example "red container" to "red box". | |
| Generator (the BT creator) | Translates the command into a tree, exactly as asked. Always returns a tree: an unclear command is read the most reasonable way, and a part none of the four actions can do is left out. Repairs a tree when it gets errors or findings back. | Ask the user anything. Check whether the plan is safe, complete or in a valid order. |
| Syntax check | Checks that the code can run: syntax, structure, arguments, that every id exists and fits its argument. | Judge what the tree means. No physical rules. |
| Semantic judge (new, LLM) | Decides with the judgement form whether the tree does what the user meant, in a physically valid way. | Write or fix trees. Judge names or code style. |

A generator that shakes an open test tube because the user did not mention closing it is
now **intended behaviour**. The judge catches it and the repair loop fixes it.

---

## 2. The new flow

```
Scene → Command → Enrichment → [ Generator → Syntax check → Semantic judge ] → Graph
```

The bracket is a loop. Every run goes through it until a tree is accepted or a cap is
reached:

| Event | What happens |
|---|---|
| Generator replies without a code block | Send it back with "Your reply contained no create_behavior_tree() code block. Return the tree." It counts as a syntax failure. |
| Syntax check fails | Send the tree and the failed checks back to the generator. |
| Judge rejects | Send the tree and the judge's form back to the generator. |
| Judge accepts | Leave the loop. Draw the accepted tree. |

**Caps** (both in `config.py`, both counted per run):

| Setting | Default | Meaning |
|---|---|---|
| `SYNTAX_FAILURE_LIMIT` | 3 | The run ends at the 3rd tree that fails the syntax check. A reply holding no code counts as one of them. |
| `JUDGE_REJECTION_LIMIT` | 3 | The run ends at the 3rd rejected tree, so the judge sees at most 3 trees. This number comes from the study design. |
| `JUDGE_FORMAT_RETRIES` | 2 | Extra judge calls when its reply is not a valid form. |

Syntax failures do not count toward the judge cap.

**Final status of a run:** `accepted`, `failed_judge_cap`, `failed_syntax_cap`,
`judge_error` (no valid form after the retries), `error` (API or stage error).

`run_generation_loop()` in `reference_loop.py` implements exactly this.

---

## 3. Changes

### 3.0 Enrichment (no change)

Enrichment stays exactly as it is in `modules/enrichment.py`, and it stays on by
default. Its job is to map the user's words to the names of the objects in the selected
scene, for example "red container" to "red box", so that the BT creator gets the scene's
names. It runs once per run, after the command and before the loop, with the selected
scene's knowledge file inserted into `scene_knowledge.txt`. The "Enrich with the scene
first" switch keeps working.

What the later stages receive:

| | Enrichment on | Enrichment off |
|---|---|---|
| Generator `COMMAND:` | the rewritten command | the typed command |
| Judge `ORIGINAL COMMAND:` | the typed command | the typed command |
| Judge `REWRITTEN COMMAND:` | the rewritten command, if it differs from the typed one | left out |

Enrichment is not repeated inside the loop. The judge treats a mapped name as correct
when it is the object the user meant: "red container" in the original and `red_box` in
the tree is not an error.

### 3.1 Generation prompt

Replace `prompts/bt_generation_prompt.txt` with the new file. The `{scene_objects}`
placeholder works as before.

Fill placeholders with `str.replace`, never `str.format`: both prompts contain literal
braces (`{e}` in the code examples, the JSON in the judge prompt).

Where the parts of the old prompt went:

| Old prompt | Now |
|---|---|
| Role, workspace, scene, the four actions | Generator, shortened. "The gripper starts closed" is removed: every action handles grasping itself. |
| Object resolution rules | Generator. New rule: "two red cuboids" out of four identical ones means the two lowest indices. |
| Tree structure rules, code requirements, output format | Generator, unchanged in substance. |
| Rule U (unclear command) | Generator, as "When the command is unclear": take the most reasonable reading and build the tree. |
| Rule A (unsupported action) | Generator, same section: leave the impossible part out and build the rest. The judge decides whether that is acceptable. |
| Close before shaking, fill before closing | Judge (physical facts). |
| "Close before placing", "pour out before placing" | Dropped. They were default orders, not physical constraints. The generator now keeps the user's order. |
| "No cap in the scene → Rule U" | Dropped. A Close without a cap to use is a missing argument, so the generator asks. |
| Rule V, final checklist | Dropped. Format is the syntax check's job, meaning is the judge's. |
| Examples 1–6 | Replaced. Made-up objects that are not in the study scenes, ids in the format `scene.py` produces, no duplicate examples, plus one repair example. |

All four code examples in the new prompt pass the current `tester.py`.

### 3.2 Generator stage (`modules/generator.py`)

- Build the user message with `generator_message()`. It always starts with
  `COMMAND:`, followed by `CLARIFICATION:` (earlier questions and answers) and
  `PREVIOUS TREE:` with either `SYNTAX CHECK ERRORS:` or `REVIEWER FINDINGS:` when
  there is something to fix. The prompt explains these sections to the model.
- `COMMAND:` is the rewritten command when enrichment ran, otherwise the typed one, as
  today.
- Read the reply with `parse_generator_reply()`. A code block is a tree; anything else
  is `no_code`.
- A reply without a code block is a failed attempt, not a question. Send it back with
  "Your reply contained no create_behavior_tree() code block. Return the tree." and
  count it toward `SYNTAX_FAILURE_LIMIT`. There is no tree to attach, so the message
  carries the demand alone.

### 3.3 No questions

The generator never asks anything, and nothing in a run waits for a person. An unclear
command is handled inside the generation prompt instead: take the most reasonable
reading, use the lowest index among identical objects, choose a reasonable number when
one is missing, and leave out a part that none of the four actions can do. Whether that
reading was acceptable is the judge's decision.

### 3.4 Syntax check (`modules/tester.py`)

- **Remove `scene.spill`** from the checks the pipeline acts on. It is a physical rule
  and now belongs to the judge. Example 1 of the new prompt triggers it today.
  Optional: keep the function and write its result to `analysis_labels.json` per
  attempt, as an automatic label for later analysis. Never send it to the generator or
  the judge, and never let it change a status.
- **Make `structure.handler` a warning.** A different log message in the except block is
  cosmetic and should not cost a repair round.
- Keep everything else, including `scene.roles`: it checks that an id fits its argument
  type (a crate cannot be the `obj` of Place). That is the code's validity, not the plan's.
- On failure, turn the blocking checks into the feedback text with `syntax_problems()`.

### 3.5 Semantic judge (new: `modules/judge.py`)

**Its job:** look at the tree the BT creator made, fill in the judgement form, and on
Reject send the filled form back to the BT creator as feedback for the next tree.

**When:** after every tree that passes the syntax check.

**System prompt:** `prompts/semantic_judge_prompt.txt`, with `{scene_objects}` replaced
by `scene.objects_block()`. That is the same object list the generator sees.

**User message:** built with `judge_message()`:

```
ORIGINAL COMMAND: <what the user typed>
REWRITTEN COMMAND: <enriched command>      only when enrichment changed it
CLARIFICATION:                             only when there were questions
Q: ...
A: ...
BEHAVIOR TREE:
<outline_for_judge(built_tree)>
```

The judge judges against the **original** command. The rewritten command was produced by
another model and can be wrong. That is one of the errors the judge must be able to catch.

**The tree outline:** use `outline_for_judge()` on the tree the syntax check built. Each
line shows the action type, its arguments and the node name:

```
Sequence [Root]
    Shake(obj="transparent_vial", times=2) [ShakeVialTwoTimes]
    Place(obj="transparent_vial", location="grey_rack") [PlaceVialInGreyRack]
```

Do not reuse `_as_text()` from the tester: it shows only node names, not the action type.
Node names are written by the generator and can be wrong.

**The judge does not get:** the Python code, the scene photo (unless the generator also
gets it), the scene's target state, earlier verdicts, or the generator's reply text.
Every tree gets a fresh judge call.

**Output:** the judgement form as JSON (shape only; the exact schema is `JUDGE_SCHEMA`):

```
{"verdict": "accept" | "reject",
 "errors": ["goal_not_achieved", "missing_action", "wrong_order",
            "wrong_object_or_location", "missing_precondition", "not_feasible"],
 "reason": "<one sentence, empty when accepted>"}
```

| Form question | Field |
|---|---|
| Q1 – Should this Behaviour Tree be executed on the robot for this task? | `verdict` |
| Q2 – If you chose Reject, what is wrong? | `errors` (codes; `ERROR_CODES` maps each code to the form's sentence) |
| Q3 – In one sentence, explain the problem. | `reason` |

- If the model supports it, request structured output with `JUDGE_SCHEMA`. This needs an
  optional `response_format` argument in `llm.ask()`, passed through to
  `chat.completions.create`.
- Always validate the reply with `parse_judgement()`, even with structured output. It
  refuses an accept that lists errors, and a reject without errors or without a reason.
- If the reply is invalid, call again with the error appended, up to
  `JUDGE_FORMAT_RETRIES` times. After that the run ends as `judge_error`. Never accept a
  tree because the judge failed.
- **Accept:** the tree is accepted and goes to the graph stage.
- **Reject:** `reviewer_problems(form)` goes to the generator together with the tree.
- **Window:** for every attempt, show the verdict, the ticked categories as the form's
  sentences, and the reason.

### 3.6 Logging

Every attempt gets its own folder, so that nothing is overwritten. Pass it as the `tag`
to `llm.ask()`, for example `tag=f'attempts/{n:02d}/generation'`.

```
data/runs/<run id>/
├── attempts/
│   ├── 01/
│   │   ├── generation/            system_prompt.txt · user_message.txt · raw_reply.txt
│   │   ├── create_behavior_tree.py
│   │   ├── tester_report.json
│   │   ├── judge_outline.txt
│   │   ├── judge/                 one folder per call: system_prompt · user_message · raw_reply
│   │   └── judge_form.json
│   └── 02/ ...
└── summary.json                   plus everything the run folder holds today
```

Add to `summary.json`:

- the final status and every counter: generator calls, syntax failures, judge calls,
  judge rejections, judge format errors
- per attempt: whether it was code or a question, whether the syntax check passed, the
  judge form, and a field `ground_truth: null`. That field is filled in by hand
  (`"correct"` or `"faulty"`) until the simulation exists. Without it the judge cannot
  be evaluated.
- whether enrichment was on, and the model and temperature of the enrichment, the
  generator and the judge, and the caps that were used
- timestamps: command received (`t_command`), first tree that passed the syntax check
  (`t_first_valid_tree`), accepted tree (`t_accepted`)

### 3.7 Config

```python
SEMANTIC_JUDGE_PROMPT_FILE = BT_GENERATION_PROMPT_FILE.parent / 'semantic_judge_prompt.txt'
JUDGE_MODEL = BT_GENERATION_MODEL     # may be a different model; always logged
JUDGE_TEMPERATURE = 0                 # if the model rejects a temperature, omit it and log that
JUDGE_SEND_SCENE_IMAGE = False        # keep equal to BT_GENERATION_SEND_SCENE_IMAGE
JUDGE_USE_STRUCTURED_OUTPUT = True
SYNTAX_FAILURE_LIMIT = 3
JUDGE_REJECTION_LIMIT = 3
JUDGE_FORMAT_RETRIES = 2
```

### 3.8 Where things are in the current code

| File | What is there now | What changes |
|---|---|---|
| `core/pipeline.py` | `Pipeline.run()` runs the stages in order and stops at the first `FAILED` or `REJECTED` stage (`TERMINAL`). | Scene, Command and Enrichment stay a straight sequence. Generator, syntax check and judge become the loop from section 2. |
| `gui/app.py` | `run_pipeline()` builds the stage list, drops `enrichment` when the switch is off and marks it `SKIPPED`. The model dropdown sets `generation_model`. | Keep the switch logic. Show every attempt (tree, checks, judge form) with an attempt selector, and add a second dropdown for the judge model. |
| `modules/generator.py` | `extract_code()`, and a `REJECTED` result when the reply is not code. | Keep `extract_code()`. The `REJECTED` branch becomes a `no_code` attempt (3.2). |
| `modules/tester.py` | `scene.spill` in `_check_scene()`, `structure.handler` in `_check_structure()`. | 3.4. |
| `modules/llm.py` | `ask()` writes its artifacts under `tag`. | Add `response_format`. Pass per-attempt tags. |
| `core/run_context.py` | `path()` creates missing folders. | Nothing. Nested tags such as `attempts/01/generation` already work. |

---

## 4. Do not

- Do not add physical rules, ordering rules or a self-check list back into the
  generator prompt, and do not "improve" it so it catches mistakes itself. The study
  needs mistakes to reach the judge.
- Do not let the syntax check judge meaning.
- Do not give the judge the target state, the code, earlier verdicts, or the photo when
  the generator does not get it.
- Do not let the judge write or fix a tree, and never treat a judge failure as an accept.
- Do not edit the enrichment prompt files. They are shared with contextual-asr.
- Do not fill prompts with `str.format`.
- Do not add the planner, the simulation or a human judge in this step.

---

## 5. Order of work

1. Replace the generation prompt. Add the judge prompt and the config entries.
2. Add the helpers from `reference_loop.py`, and `response_format` to `llm.ask()`.
3. Change the tester (3.4).
4. Add the judge stage (3.5).
5. Replace the straight stage sequence with the loop (section 2, `run_generation_loop()`).
6. Make sure nothing waits for a person (3.3).
7. Logging (3.6).
8. Tests (section 6).

---

## 6. Tests

### 6.1 Loop tests without API calls

Replace `modules.llm.ask` with scripted replies (pytest `monkeypatch`) and use the real
syntax check. These ten cases already pass against `reference_loop.py`. They must also
pass against the real pipeline:

| Case | Expected end |
|---|---|
| Good tree, judge accepts | `accepted`, 1 generator call, 1 judge call |
| Tree without Close, judge rejects, repaired tree accepted | `accepted`, 2 generator calls, 1 rejection. The 2nd generator message contains `REVIEWER FINDINGS:` |
| Three rejected trees | `failed_judge_cap`, 3 generator calls, 3 rejections |
| Tree with a wrong id, repaired | `accepted`, 1 syntax failure. The 2nd message contains `SYNTAX CHECK ERRORS:` and names the id |
| Three trees that fail the syntax check | `failed_syntax_cap`, judge never called |
| A text reply, then a good tree | `accepted`, 1 syntax failure. The 2nd message asks for the code block |
| Three text replies | `failed_syntax_cap`, judge never called |
| Invalid judge reply, then a valid accept | `accepted`, 2 judge calls, 1 format error |
| Three invalid judge replies | `judge_error`, 3 judge calls |

### 6.2 Live smoke tests

Run each once with the real model and report the final status, the number of attempts
and every judge form.

Tests 2 to 4 run with enrichment **off**, so that the command reaches the BT creator as
typed and only the BT creator and the judge are tested. Tests 1 and 5 run with
enrichment **on**.

1. **Cuboid scene:** "Place two red cuboids into the dark green crate on the right side."
   Expected: Place `red_cuboid_1` and `red_cuboid_2` into `dark_green_crate_2`, accepted.
2. **A scene with a test tube that holds liquid, and a cap:** "Shake the test tube two
   times." Expected: the BT creator returns Shake without Close, the judge rejects with
   `missing_precondition`, and the repaired tree has Close first and is accepted. This
   proves that the validation moved from the BT creator to the judge.
3. Same scene: "Shake the test tube a few times." Expected: a tree that shakes one test
   tube a reasonable number of times, with no question asked.
4. Same scene: "Stir the liquid in the test tube." Expected: stirring is left out. With
   nothing else to do, the tree is empty or minimal, and the judge decides.
5. **Cuboid scene, enrichment on:** "Put one red block into the green container on the
   right." Expected: the rewritten command uses the scene's names (cuboid, dark green
   crate), the tree places one red cuboid into `dark_green_crate_2`, and the judge
   accepts it even though the user said "block" and "container".

---

## 7. Open points (defaults are set, all in `config.py`)

- The cap for syntax failures (3). The judge cap (3) comes from the study design.
- Whether the judge uses the same model as the generator or a different one.
- Whether both models should get the scene photo. If one gets it, the other must too.
