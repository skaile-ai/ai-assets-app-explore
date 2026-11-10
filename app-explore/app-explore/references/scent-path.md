# Feature `scent_path`

Read this only when `run.json.features.scent_path` is true. It adds `pathScent` to step 6, the path findings of step 7 and the `Step` rows of `scent_table`. Cost: one judge call per path state and group of marks.

## Step 6: `pathScent`

`pathScent` repeats the scent check on every state of each task's shortest path, the entry included, the way a user scans. The state's marks are taken in reading order (rows top to bottom, left to right), at most `scent.max_marks`, and cut into groups of `scent.chunk_size` (rubric.json). The judge sees one group at a time with the persona, the task, the step and the clicks so far, and picks one of the group's marks or `next`; `next` shows the following group in the next round. Every call is a judge call of kind `path_scent`.

It adds `steps[]` to each task in `scent.json`, one per path state:

- `step` (0 = entry), `state`, `chunk` (group of the pick, 1-based), `chunks`, `p`;
- `predicted` (mark; `null` = nothing on this screen), `expected` (the path's marks), `expected_chunk`;
- `correct` (as for the entry), `premature` (wrong pick in a group before the right mark's group).

`sp.judge_error` set: the judge died; the unanswered steps carry `error: "judge unavailable"`; rerun `pathScent` once the judge is back.

**Done when** each `scent.json` entry has `steps[]` with one entry per path state, and `run.json.models` has `calls` for `path_scent` when a task has a path.

## Step 7

A task's `steps[]` replace its entry check: each wrong step gives `S-scent` on that step's screen (the text names the step), or `S-premature` when the pick came in an earlier group than the right mark.

## Step 9

`scent_table` has one row per path step (`Step` column), `too early` for `S-premature`.
