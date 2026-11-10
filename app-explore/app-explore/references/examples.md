# Feature `examples`

Read this only when `run.json.features.examples` is true. It changes the critic brief of step 8, the critic findings of step 7 and adds a `run_details` row in step 9. No extra model call; the critic prompt gets longer.

## Step 8: the critic brief

`criticBrief` adds the picked example critiques and, per state, the ids of the examples matched to the judge's `screen_type` answer (how many: rubric.json `examples.per_screen`). The bank is `examples/critiques.json`: critiques adapted from UICrit (CC BY 4.0, see `examples/ATTRIBUTION.txt`) plus critiques from earlier app-explore runs. The UICrit examples come without their RICO screenshots: the critic reads their text and box as the description, and the brief needs no image.

Every critic finding then carries a `box` (`{x, y, w, h}` in viewport percent) and `example_ids` (`[]` when no example applied).

**Done when** every finding in `critique/c1.json` has `box` and an `example_ids` array (`[]` counts: no example applied to that finding).

## Step 7

A critic finding gets `box` (without marks its pin sits at the box centre) and `example_ids`. A critic finding with neither a box nor a known mark goes to `needs_check.json`.

## Step 9

`run_details` names the critic's example bank and its UICrit attribution (CC BY 4.0) when a critique exists.
