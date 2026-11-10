# Feature `seq`

Read this only when `run.json.features.seq` is true. The walkers (agent and kernel) then rate every step on the Single Ease Question (SEQ, 1 very difficult to 7 very easy) and answer the 10 SUS items after the task; both texts are in rubric.json `seq`. No extra model call.

## Step 7

- `W-friction` findings (source `seq`, one per state and task, id `W-friction@<8 hex>-<task id>`) on the state of every walk step rated SEQ ≤ `max_seq` or at least `min_drop` below the step before (rubric.json rule thresholds).
- `tasks.json` rows gain `seq` (per step, 1-7), `seq_labels` (each step's label from the same walk), `seq_missing` (per walk, keyed by task id or variant id: how many of its steps lack a valid SEQ), `sus` (0-100: 2.5 × Σ odd items x−1, even items 5−x; `null` without 10 valid answers or when answered by pattern) and `sus_suspect`.
- A walk is `sus_suspect` when its SUS answers follow a pattern (rubric.json `seq.sus_suspect`: all equal, or alternating perfectly). It is left out of every SUS mean; `scores.json` `app.sus_suspect` and, with feature `personas` > 1, `tasks.json` `sus_suspect_walks` count them.
- `scores.json` `app` gains `sus` (mean) and `sus_personas`; `diff.json.tasks` briefs carry `sus`. Guard-blocked walks (`blocked_by_guard`, SKILL.md step 8) count in neither SEQ nor SUS.

**Done when** every `seq_missing` count is 0; a step without SEQ means the walker skipped its rating, so redo that walk.

## Step 9

- `tasks_table` gains a SUS column (with `since`: "now (was prev)"; a walk answered by pattern is named in the cell).
- `seq_tabs` (tabs): per walked task a `bars` chart of its steps' SEQ, coloured by the `W-friction` rule (red at or below `max_seq`, yellow below `chart_yellow_below`).
