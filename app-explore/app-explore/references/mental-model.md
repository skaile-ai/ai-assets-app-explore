# Feature `mental_model`

Read this only when `run.json.features.mental_model` is true. It adds step 6b (after step 6), step 8b (after step 8), the `M-expectation` findings of step 7 and the `mental_growth` and `mental_table` blocks of step 9. With the feature off `mentalModel` returns `{ skipped }` and writes nothing.
Cost: per replayed crawl edge one `smol` prediction, one judge match and one `smol` update; per walk one `smol` update plus a judge match per free-text outcome.

A simulated first-time user knows only what it has seen. Its **concepts** are the objects, places and actions it believes exist (`believed_attributes`, `seen_in`, `confidence`, `first_seen`, and `found_via`: the label of the click that first showed it, `null` for the entry screen). Its **violations** are the moments the app broke what it expected.

## 6b. Grow the model along the crawl

```js
const mm = await ap.mentalModel({ judgeBatch, completion }, { dataDir });   // { edges, of, concepts, violations, unsure, errors }
```

`mentalModel` replays the crawl edges in BFS order from the entry state, at most `rubric.json` `mental.max_edges`. Per edge it makes three cheap calls:

1. `smol` predicts from the model so far and the clicked label what the click will show: kind, heading, object, purpose (`mental_predict`).
2. The judge decides `matches` between that prediction and the target state's screenshot plus perceive extract (`mental_match`, gated like every bool; undecided = `null`).
3. `smol` updates the concepts and logs contradictions (`mental_update`).

`<stem>.data/mentalmodel.json` = `{cap, concepts, timeline, violations, after_crawl, errors?}`:

- `cap` = `{edges, total_edges, replayed, truncated}`. `truncated: true` means the crawl had more edges than the cap, so the deepest screens got no prediction. Tell the user; to cover them, raise `mental.max_edges` in rubric.json (or pass `maxEdges`) and run this step again.
- `timeline[]`: one entry per step (0 = the entry state) with `state`, `label`, `predicted`, `matches`, `p`, `added`/`confirmed`/`contradicted`, `concepts` (count so far) and the ids of its `violations`.
- `violations[]`: `id`, `kind`, `source` (`crawl` | `walk`), `state`, `label`, `expected`, `observed`.

The four violation kinds:

- `expectation`: the click showed another thing than its label promised.
- `affordance`: the control looked like one kind of control and acted like another, e.g. a project link that only expands the sidebar.
- `location`: a known thing turned up where the user did not expect it.
- `naming` (`names`): one thing under two names (`same-object-different-name`), or one name for two things (`same-label-different-target`).

A miss's kind comes from the update; contradictions on a step that already missed are dropped as repeats.

`mm.errors > 0`: `mentalmodel.json` `errors` names the step and call kind; a judge outage leaves `matches: null` on those steps and adds no violation. Re-run this step once the judge answers; it rewrites the file.

**Done when** `mentalmodel.json` exists with one `timeline` entry per replayed edge plus the entry, `run.json.models` has `calls` for `mental_predict`, `mental_match` and `mental_update`, `mm.errors` is 0, and a `cap.truncated: true` was reported to the user.

## 8b. Feed the walks into the model

The walks show what a user expected before each click (`expected`) and what happened (`outcome`).

```js
const mw = await ap.mentalModel({ judgeBatch, completion }, { dataDir, pass: 'walks' });   // { walks, steps, concepts, violations, walk_violations, errors }
```

`pass: 'walks'` restarts from the crawl's model (`after_crawl`) and feeds the base walks (`walks/<task>.json`) in turn, at most `mental.max_walk_steps` steps in all. Persona variants (walk files with a `variant` field) are skipped, so the model stays one person's and the cap goes to the base walks. Per step:

- an `as-expected` / `unexpected` outcome decides the match directly;
- the judge decides free-text outcomes (`mental_match`); a step it could not judge is listed in `errors`;
- `blocked` steps count for nothing.

One `smol` update per walk (`mental_update`) adds the walk's concepts and the kind of every miss. The pass keeps the crawl part of the timeline and violations and rewrites the walk part, so it is safe to repeat after a walk is redone. `mentalmodel.json` `walks.truncated: true` means steps past `mental.max_walk_steps` were left out; raise it in rubric.json and repeat to include them.

Then run `analyze.py` again exactly as in step 7: walk violations become `M-expectation` findings with their task.

**Done when** `mentalmodel.json` has a `walks` entry (`fed` = the walk files with expectations), one `timeline` entry per fed walk (source `walk`), `mw.errors` is 0, and the re-run `findings.json` holds an `M-expectation` finding for every violation whose state or task resolves.

## Step 7: `M-expectation`

With `mentalmodel.json` present, `analyze.py` adds one `M-expectation` finding per state and violation kind (source `mental`, id `M-expectation@<8 hex>-<kind>`, `violations`: the violation ids, `tasks` for walk ones; severity per kind from rubric.json).
It sits on the state the click led to; a walk step that left the crawled graph lands on its task's `target_state`, else the entry, and the text names the URL. A `naming` violation whose two names already are one object's labels, or a pair `synonyms.json` judged two different things, adds nothing. An undecided crawl match (`matches: null`) goes to `needs_check.json` together with the violations the update logged on that step; none of them becomes a finding.

## Step 9 blocks

- `mental_growth` (bars): concepts a first-time user knows after each crawl click and each walk, red where the step broke an expectation (its `p` says so).
- `mental_table` (table): every violation with kind, crawl or task step, the screen it happened on (links to its gallery shot and pins) and its `M-expectation` finding.
