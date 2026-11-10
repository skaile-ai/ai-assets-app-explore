# Feature `personas` (n > 1)

Read this only when `run.json.features.personas` is above 1. With n = 1 variant files are ignored and every output is the single-walk one. Cost: n-1 × tasks × up to 16 `smol` calls (kernel walks).

## Step 6: variants

`synthesize` gives every persona n-1 **variants** in the same call: other people in the same role, spread over digital literacy, hurry and prior domain knowledge (`{id: "<persona id>-v<k>", name, literacy, hurry, domain, note}`, value lists in rubric.json `personas`). `m.variants` counts them and `m.variants_short` lists personas that got fewer.

## Step 8: variant walks

The walker agent stays one per task. The other n-1 walkers of a task are its persona's variants, walked in the kernel by `walk.mjs` on `smol`, each playing its variant and writing `walks/<task id>-<variant id>.json` (with `variant`). `walkAll` runs them in parallel up to rubric.json `personas.walk_concurrency` and skips every walk whose file exists, so calling it again redoes only missing or deleted ones:

```js
const fan = await wk.walkAll({ ax, browser, completion, url: run.url, mode: run.mode, dataDir });
```

`fan.errors` lists the walks that threw (`{task, variant, error}`); call `walkAll` once more for them.

**Done when** `walks/` has, besides the base walk per task, one file per task and variant of its persona (n-1 per task), after the second `walkAll` at the latest.

## Step 7: findings on the success rate

A task's walks are its base walk `walks/<task>.json` plus its variant walks `walks/<task>-<variant>.json`.

- `W-failed` fires when the task's success rate is at most `max_rate`; else `W-struggle` when at least `min_share` of its walks failed or struggled (rubric.json rule thresholds). The finding carries `rate` and `walks`, names who failed and sits where the first of them ended. A task with one walk keeps the single-walk text.
- `W-friction` covers every walk.
- `tasks.json` rows gain `walks`, `successes`, `rate`, `rate_ci` (Wilson 95 % interval, z = rubric.json `personas.wilson_z`), `clicks_median`, `clicks_range`, `ease_median`, with `seq` also `sus_mean` and `sus_range`.
- `scores.json` `findability` uses the rate per task over all its walks, and its SUS counts every walk.
- `diff.json.tasks` briefs carry `walks`, `rate`, `rate_ci` (and `sus_mean`).

## Step 9: `tasks_table`

Walk result as successes/walks with the 95 % interval ("2/3 (21-94 %)"), clicks as median (range), median ease, SUS as mean (range); with `since` the previous successes/walks and SUS as "now (was prev)".
