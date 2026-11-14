# Dynamic creator

Mode id `dynamic_creator`. Defined in `modules/modes.py`.

## 1. What this mode is

The creator is given what only the judge gets in the Static creator & Dynamic judge
mode: the scene object list and the physical facts. It is asked to make the tree
physically possible itself, and nothing judges it. A tree that fails the syntax check is
sent back for repair; the first tree that passes it is the result. It is compared
against:

- **Static creator**: the same loop, and neither has a judge. The only difference is what
  the creator is given (the scene, the physical facts, and the job of checking its own
  tree);
- **Static creator & Dynamic judge**: there the same knowledge sits with a separate
  judge that can send the tree back up to three times. Here it sits with the creator, who
  gets one try plus syntax repairs (see `modes/README.md`).

The tree is still generic. The creator is shown today's table so that it can check its
tree against it, but it may not name an object, and the syntax check refuses any object
id in the tree, as in every mode.

## 2. What the creator sees

The system prompt is `modes/dynamic_creator/creator_prompt.txt`. It is the Static
creator's prompt with five changes and nothing else (`git diff --no-index
modes/static_creator/creator_prompt.txt modes/dynamic_creator/creator_prompt.txt` shows
them all). In order:

| Part | From |
|---|---|
| The role: write a behavior tree in XML from one command, never ask questions | `creator_prompt.txt` (as the Static creator) |
| The tree is generic: **changed**, "You are shown the objects on today's table so that you can check what your tree does on it, but the tree never names a particular object, and it must not depend on what happens to be on this table." | `creator_prompt.txt` |
| The job: **changed**, make a tree the robot can physically carry out, add the steps the physical facts make necessary; "Nobody checks the tree after you"; check the tree against the scene and the physical facts before answering | `creator_prompt.txt` |
| Robot and workspace | `prompts/shared/robot_and_workspace.txt` |
| What the robot perceives | `prompts/shared/perception.txt` |
| **Added:** Scene, the object list of this scene (`{scene_objects}`), "Use this list only to check what your tree does on this table. Never write these ids in the tree" | `creator_prompt.txt` + `modules/scene.py: Scene.objects_block()` |
| Writing a tree in XML · The blackboard · Finding and checking objects | `creator_prompt.txt` (as the Static creator) |
| Actions | `prompts/shared/generic_actions.txt` |
| **Added:** Physical facts | `prompts/shared/physical_facts.txt` |
| Decorators | `creator_prompt.txt` (as the Static creator) |
| Describing the objects the command needs: **changed** first rule, "add only the properties the physical facts make necessary, such as graspable="True" for objects that will be picked up" | `creator_prompt.txt` |
| Where to find objects · Building the tree · Choices, fallbacks and failures · XML format | `creator_prompt.txt` (as the Static creator) |
| Follow-up messages: **changed**, only `SYNTAX CHECK ERRORS:` can follow a previous tree (no reviewer findings) | `creator_prompt.txt` |
| Output | `creator_prompt.txt` (as the Static creator) |

- **The scene object list: yes.** The same eight lines for scene8 as the judge gets in
  mode 2 (see `modes/static_creator_dynamic_judge/README.md`, section 3).
- **The physical facts: yes.** Every line of `prompts/shared/physical_facts.txt`.
- The word "reviewer" does not appear: there is none.
- No judge's judgements are given to it; there is no judge, and no second model call
  that checks the tree.
- No scene photo (`config.BT_GENERATION_SEND_SCENE_IMAGE = False`).

`BTGenerator.system_prompt()` raises a `StageError` if this mode's prompt ever loses its
`{scene_objects}` placeholder, so a Dynamic creator can never quietly run without the
scene.

## 3. What the judge sees

This mode has no judge.

## 4. The first message

From run `data/runs/dynamic_creator/2026-11-14_12-17-55_c708` (scene8),
`attempts/01/generation/user_message.txt`:

```
COMMAND: shake the test tube 3 times
```

The same message as the other modes. The difference is in the system prompt. The tree
that came back (`attempts/01/tree.xml`):

```xml
<root main_tree_to_execute="MainTree">
  <BehaviorTree ID="MainTree">
    <Sequence name="Root" memory="true">
      <FindOne name="FindGraspableTestTube" key="tube" type="test tube" graspable="True"/>
      <FindOne name="FindCapForTestTube" key="cap" type="test tube cap" graspable="True"/>
      <Selector name="EnsureTubeIsClosed" memory="true">
        <HasProperty name="TubeIsClosed" obj="{tube}" property="closed" value="True"/>
        <Sequence name="CloseTubeSequence" memory="true">
          <Close name="CloseTube" obj="{tube}" closing_obj="{cap}"/>
        </Sequence>
      </Selector>
      <Shake name="ShakeTube" obj="{tube}" times="3"/>
    </Sequence>
  </BehaviorTree>
</root>
```

It closes the tube before shaking it without being told to, which is a step the physical
facts make necessary. On the mock world it ends in SUCCESS with no fault.

## 5. What comes back on a repair

Only syntax problems, exactly as in the Static creator mode: `PREVIOUS TREE:` followed by
`SYNTAX CHECK ERRORS:`, or the no-code message (see `modes/static_creator/README.md`,
section 5).

## 6. How a run ends

One cap applies: `config.SYNTAX_FAILURE_LIMIT = 3`.

| Final status | When |
|---|---|
| `no_judge` | a tree passed the syntax check; it is the result, not judged |
| `failed_syntax_cap` | the 3rd tree (or reply without code) failed the syntax check |
| `error` | the run stopped with an error, for example the placeholder check above |

## 7. Where its runs are

`data/runs/dynamic_creator/<run id>/`, with the same files as a Static creator run (see
`modes/static_creator/README.md`, section 7). `summary.json` says `dynamic_creator` in
`mode` and `loop.mode`; `loop.models.judge` is `null`; `loop.models.generator.prompt` is
`modes/dynamic_creator/creator_prompt.txt`. Each attempt folder holds `generation/`
(`system_prompt.txt`, with the scene in it, `user_message.txt`, `raw_reply.txt`),
`tree.xml` and `tester_report.json`. There are no old runs of this mode.

## 8. The files in this folder

- `README.md`: this description.
- `creator_prompt.txt`: the creator's system prompt.
