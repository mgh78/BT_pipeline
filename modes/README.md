# The three modes

A run is made in one of three modes. The code is shared: one generator, one judge, one
loop, one syntax check. A mode decides only which creator prompt is loaded and whether
the judge is called (`modules/modes.py`). Every mode writes **generic** trees: no object
id in the tree, objects found by their properties, and the same tree should do the task
on any table.

| Mode id (code, folders, `summary.json`) | Title (window, README) | Creator sees | Judge |
|---|---|---|---|
| `static_creator` | Static creator | the command only | none |
| `static_creator_dynamic_judge` | Static creator & Dynamic judge | the command only | sees the scene and the physical facts; up to 3 rounds |
| `dynamic_creator` | Dynamic creator | the command, **the scene object list and the physical facts** | none |

- **Static creator** ([README](static_creator/README.md)): the creator gets the command
  and the shared description of the robot, the perception, the XML grammar and the
  actions. There is no judge.
- **Static creator & Dynamic judge**
  ([README](static_creator_dynamic_judge/README.md)): the same creator, the same prompt
  word for word. The judge gets the command, the tree's outline, the scene object list
  and the physical facts, and sends a rejected tree back with its findings.
- **Dynamic creator** ([README](dynamic_creator/README.md)): the creator gets
  everything the Static creator gets, plus the scene object list and the physical facts,
  and is told that nothing checks its tree. There is no judge.

In every mode a tree that fails the syntax check goes back to the creator, up to
`config.SYNTAX_FAILURE_LIMIT` (3). The default mode is `config.DEFAULT_MODE`
(`static_creator_dynamic_judge`). Runs are saved in `data/runs/<mode id>/<run id>/`.

## How to compare them

Mode 1 against mode 2 changes one thing, the judge. Mode 1 against mode 3 changes one
thing, what the creator is given. Mode 2 against mode 3 changes **two** things at once:
where the knowledge about the table and the physics sits (with a separate judge, or with
the creator), and how many tries there are (mode 2's creator can be sent back up to
three times by the judge; mode 3's creator gets one try, plus syntax repairs). So a
better result in mode 2 than in mode 3 may come from the extra tries rather than from
the knowledge being in a separate model. Read mode 2's runs together with how many
attempts each one needed: `loop.attempts` and `loop.counts` (`generator_calls`,
`judge_rejections`) in `summary.json`. A mode 2 run accepted on its first attempt had
the same number of tries as a mode 3 run.
