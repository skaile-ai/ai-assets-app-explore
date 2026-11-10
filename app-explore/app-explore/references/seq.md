# Feature `seq`

Read this only when `run.json.features.seq` is true. The walkers (agent and kernel) then rate every step on the Single Ease Question (SEQ, 1 very difficult to 7 very easy) and answer the 10 SUS items after the task; both texts are in rubric.json `seq`. No extra model call.

## Step 7

- `W-friction` findings (source `seq`, one per state and task, id `W-friction@<8 hex>-<task id>`) on the state of every walk step rated SEQ ≤ `max_seq` or at least `min_drop` below the step before (rubric.json rule thresholds).
- `tasks.json` rows gain `seq` (per step, 1-7), `seq_labels` (each step's label from the same walk) and `sus` (0-100: 2.5 × Σ odd items x−1, even items 5−x; `null` without 10 valid answers).
- `scores.json` `app` gains `sus` (mean) and `sus_personas`; `diff.json.tasks` briefs carry `sus`.

## Step 9

- `tasks_table` gains a SUS column (with `since`: "now (was prev)").
- `seq_tabs` (tabs): per walked task a `bars` chart of its steps' SEQ, coloured by the `W-friction` rule (red at or below `max_seq`, yellow below `chart_yellow_below`).
