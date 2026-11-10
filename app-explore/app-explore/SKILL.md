---
name: app-explore
description: Explore a running web app like a user and report its perceived
  objects, tasks, navigation and visual clarity with an annotated screenshot
  gallery. Use for 'explore my app', 'how clear is my app', 'UX audit of <url>',
  or re-running against a previous app-explore report.
license: MIT
metadata:
  version: 0.1.0
  publisher: skaile-ai
  requires: "report"
---

# app-explore <url> [sandbox] [since <path>|since auto] [budget <n>] [with <f,…>] [without <f,…>] [personas <n>]

You explore a running web app the way a first-time user would, without its source code: a hidden browser crawls every reachable **state** (a page, or a dialog, menu or tab panel opened by a click), each state gets a screenshot plus a Set-of-Mark screenshot where every interactive element carries a numbered **mark**, and the run ends in a static HTML report built with the `report` skill. Needs `@skaile-ai/report` ≥ 0.6.0 (gallery block, `app-audit` profile) and, for the walk and critique steps, the agents `app-explore-walker` and `app-explore-critic`.

The browser and model work lives in `crawl.mjs`, `pipeline.mjs` and `walk.mjs` beside this file, the feature switches and model roles in `config.mjs`. Resolve this skill's directory once (omp deploys skills under `~/.agents/skills/` or `~/.omp/agent/skills/`) and import from it in a JavaScript `eval` cell; the functions take the tab (or the eval `browser`, `judgeBatch`, `completion`) as arguments:

```js
const { existsSync } = await import('node:fs');
const helpers = [`${process.env.HOME}/.agents/skills/app-explore`, `${process.env.HOME}/.omp/agent/skills/app-explore`]
  .find((d) => existsSync(`${d}/crawl.mjs`));
const ax = await import(`${helpers}/crawl.mjs`);
```

`<skill dir>` in shell commands below is that same `helpers` path.

The app's data is someone's real data. The run is **readonly** by default: a write guard in the page and a deny-list keep the crawler's and walkers' own clicks from writing; step 3 has the exact rule and the writes it still lets through. `sandbox` lifts guard and deny-list for an app whose data may change; logout stays denied in every mode.

## 1. Arguments and stem

Parse `app-explore <url> [sandbox] [since <path>|since auto] [budget <n>] [with <f,…>] [without <f,…>] [personas <n>]`:

- `mode`: `sandbox` when the word is present, else `readonly`.
- Reports dir: `<repo>/.scratch/reports/` with repo = `git rev-parse --show-toplevel` of the cwd, else `~/.scratch/reports/`.
- **Stem**: `app-explore-<host>-<YYYY-MM-DD>`, with `-v2`, `-v3` … appended when that stem's `.json` or `.data/` already exists. `<host>` is the URL hostname without `www.` (`localhost` stays `localhost`).
- `since auto`: among stems `app-explore-<host>-<date>[-vN]` in the reports dir other than this run's that have both a `<stem>.json` report file (not `<stem>.choice.json`) and a `<stem>.data/` dir, the one whose `<stem>.json` was modified last; `since <path>`: that file. Its `<prev stem>.data/` and `<prev stem>.media/` must exist, else stop with `since: <path> has no .data/ dir`. `since` (for `run.json` and every later step) = the absolute path of that `<prev stem>.data/` dir. No `since`: `since = null`.
- `budget <n>`: sets `budgets.states`, the crawl's state budget (default 60):

```js
const budgets = { states: budget ?? 60, depth: 5, perRoute: 2, actions: 25, minutes: 20 };
```

- `with <f,…>` / `without <f,…>` switch the features below on or off (comma list of names); `personas <n>` sets how many personas walk each task. Resolve them against the defaults in `rubric.json` `features`; an unknown name or a bad `personas` throws with the valid names: stop and show the user that message.

```js
const cfg = await import(`${helpers}/config.mjs`);
const features = cfg.resolveFeatures(await cfg.readRubric(), { with: withList, without: withoutList, personas });   // absent: [], [], undefined
```

|Feature|Default|Gates|Cost|
|---|---|---|---|
|`examples`|on|step 8 critic: four example critiques per screen matched to its screen type (`examples/critiques.json`, UICrit CC BY 4.0 + own runs); every critic finding carries a `box` or marks, else it goes to `needs_check`; step 9 `run_details` names the UICrit attribution|longer critic prompt, no extra call|
|`seq`|on|step 8 walks: SEQ 1-7 per step and the 10 SUS items after the task; `W-friction` findings, SUS in the report|no extra call|
|`personas <n>`|3|step 6: `n-1` persona variants per persona; step 8: per task one walker agent plus `n-1` kernel walks with those variants; steps 7 and 9: walk findings and the tasks table on the task's success rate|`n-1` × tasks × up to 16 `smol` calls|
|`scent_path`|on|step 6 scent: every state along each task's shortest path, marks in reading order in chunks of 8; `S-premature` findings|one judge call per path state and chunk|
|`mental_model`|on|steps 6b and 8b: a first-time user's model grown along crawl edges and walks (`mentalmodel.json`); step 7 `M-expectation` findings; step 9 `mental_growth`, `mental_table`|per crawl edge (≤ `mental.max_edges`) one `smol` prediction, one judge match, one `smol` update; per walk one `smol` update plus a judge match per free-text outcome|
|`saliency`|off|step 5b: the local UMSI++ model scores each screenshot (`saliency.json`, `<id>.sal.png` heatmaps); step 7 `R-salience` findings; step 9 `saliency_gallery`|one-time install of about 1.5 GB in `~/.cache` (needs python3.11); about 0.15 s CPU per screen, no model call|

`run.json.features` is the run's only record of the switches: every later step reads it (`await cfg.features(dataDir)`), never the arguments. A switch whose step does not read it has no effect, and a feature that is off writes no file and adds no finding.

Every model call takes its role from `rubric.json` `models`, one role per call kind: `judge` (the cheap judge, `judgeBatch`) for bool, choice and score questions; `smol` for extraction, short generation and kernel walks; `slow` only for synthesis and the critic. Change a role there, never in code. Each call is counted into `run.json.models[<kind>]` = `{role, calls, secs}` (plus `cost` when the judge reports one), summed across cells.

Files of the run, all under the reports dir: `<stem>.data/` (every data file), `<stem>.media/` (screenshots), later `<stem>.json`, `<stem>.choice.json`, `<stem>.html`. Write `run.json` now:

```js
await ax.writeRun(dataDir, { url, started: new Date().toISOString(), mode, since, budgets, features, viewport: { width: 1280, height: 800 } });
```

**Done when** `<stem>.data/run.json` exists with `url`, `started`, `mode`, `since`, `budgets` and `features` (every key of `rubric.json` `features`), and a non-null `since` names an existing previous `.data/` dir with `graph.json`.

## 2. Open the app and get past the login

```js
const o = await ax.openApp(browser, { url, dataDir, mode });   // tab "explore", hidden managed Chromium, 1280×800
```

`openApp` opens the tab through `ax.openGuarded` (each walk in step 8 opens its tab the same way), which installs the write guard (step 3) before anything loads: it opens the tab on `about:blank`, calls `readOnly`, loads `<stem>.data/auth.json` when present, then navigates to the URL and waits until the app has rendered, so even the app's first requests run under the guard. `openApp` then detects a login wall (URL path contains login/signin/sign-in/auth, or a visible password field) and borrows the session from the user's Chrome: it opens the URL in a relay tab, exports cookies and storage to `auth.json` with `saveState`, closes the relay tab, loads the state into the guarded managed tab and navigates again. The user's Chrome only ever serves this export; the crawl runs in the managed tab.

`o.login === true` means the user's Chrome has no session either: `openApp` reopened the tab headed. Tell the user in one chat line to sign in in the browser window that just opened, then run `await ax.waitLogin(o.tab, { dataDir })`, which waits until the login wall is gone and saves `auth.json`. Write the language: `await ax.writeRun(dataDir, { lang: o.lang, auth: o.auth })` (`de` when `<html lang>` starts with `de`, else `en`).

`auth.json` holds live session cookies: it stays inside `<stem>.data/` and never goes into a commit, a report or a chat message.

**Done when** `ax.isLogin(o.tab)` is false on the app's start page and `run.json` has `lang`.

## 3. Write guard

The guard is already in place from step 2. In readonly mode it is an init script over `fetch`, `XMLHttpRequest`, `sendBeacon` and form submits that also answers "really?" confirms with no. Readonly means the crawler's and walkers' own clicks never write; the page itself still POSTs while it loads, and those writes pass. Every crawler click or key press is preceded by `ax.act(tab)`, which opens a 2-second **acting** window in the current document: inside it every write is rejected except POSTs matching an `allowPost` regex string, GraphQL bodies without `mutation`, and tRPC calls whose procedures all start with a read verb followed by a camelCase capital, `_`, a digit or the name's end (`getUser`, `list`; not `issueRefund`, `checkout`); outside it (page loads, timers) POST passes and PUT, PATCH, DELETE are still rejected. `tab.route` cannot filter by method, so the guard lives in the page. The deny-list (`ax.denied`) matches whole words at a word start (`Save`, `Delete project`, `Cancel order`, `Projekt löschen`; not `Saved items`, `Absender`, a lone `Cancel`).

A passing load-time POST is not harmless by definition: it can create or change data (an app that creates a default project on first visit does so under the guard too). The guard cannot tell a bootstrap write from a read-only POST; it records them in `passive.jsonl` (`why: passive`), and the user decides what they mean. So an empty `leaks.jsonl` never means the data is unchanged: in readonly mode the chat shows the user the distinct passive write procedures (`procs`, step 4) after the crawl and again after the walks (step 8).

When a screen breaks because a click needs a read-only POST the rules miss (a search endpoint), replace the guard with that endpoint allowed; this reloads the page under the new guard:

```js
await ax.readOnly(o.tab, { mode, dataDir, allowPost: ['/api/search'] });
```

Rejections land in `<stem>.data/blocked.jsonl`, writes the guard let through in `passive.jsonl` (`why`: passive, allow, graphql, trpc), writes that reached the server without such a pass in `leaks.jsonl`. Each row has `method`, `url`, `state` (the id of the state whose page made the write; `null` before the first state and in walks), `task` (the walk's task id; `null` in the crawl) and `page` (the URL it was made on); `analyze.py` places a leak without `state` on the state whose url, path or route matches `page`. The crawl calls both functions after every state; a step that drives its own tab calls them the same way:

```js
const nBlocked = await ax.drainBlocked(tab, dataDir, { state });       // state id or null (walks: { task }); returns rows moved to blocked.jsonl
seq = await ax.auditLeaks(tab, dataDir, seq, { state });              // drains first; seq per tab: start 0, pass the returned seq next time
```

**Done when** `blocked.jsonl`, `passive.jsonl` and `leaks.jsonl` exist and, in readonly mode, `await ax.guardCheck(o.tab, dataDir, mode)` returns `app-explore: blocked DELETE` (its `blocked.jsonl` row has `why: "selfcheck"` and counts nowhere).

## 4. Crawl

Run the crawl in a cell with `timeout: 0`; it keeps the budget itself:

```js
const counts = await ax.crawl(o.tab, {
  dataDir, mediaDir, start: url, mode,
  seeds,                          // [] without since; with since: the previous run's page urls, below
  budgets,                        // from step 1
  log: (line) => console.log(line),
});
```

With `since`, seed the crawl with the previous run's pages so every screen it saw is visited again (dialogs and menus come back through their pages):

```js
const prevGraph = since ? JSON.parse(await Bun.file(`${since}/graph.json`).text()) : null;
const seeds = prevGraph ? [...new Set(prevGraph.states.filter((s) => s.kind === 'page').map((s) => s.url))] : [];
```

Seeds are visited right after `start`, before any breadth-first expansion: the start page's (and each seed's) tab, popup and button clicks wait until every seed page is captured, so a small `budget` re-checks the previous run's first pages and leaves the rest as removed screens.

The crawl is breadth-first from `start`. Per state it waits until the network is quiet, computes the state **key** (route, kind, heading, interactive labels) and skips known keys and routes already holding `perRoute` states (that state's `instances` grows instead). A new state gets `<id>.png`, `<id>.som.png` (marks drawn), `<id>.mobile.png` (pages at depth ≤ 1, 390×844), `screens/<id>.json` (aria snapshot, visible text, marks, geometry: overflow, overlap, small targets) and a dHash. Pages expand by their links (nav first) and by clicking tabs, popup triggers and other buttons; a click that opens a dialog, menu or tab panel records a leaf state and queues its links. `graph.json` is rewritten after every state, so an interrupted crawl keeps what it saw.

Read the `log` lines and `counts` as they come back:

- `states` far below the budget and `queued: 0`: the app exposes few links; check `screens/s01.json` marks for navigation that is not an `<a href>` (it reached the crawl only through button clicks).
- Many states with the same heading and different routes: item pages whose slug ids the `:id` pattern did not collapse eat the budget; raise `budgets.states` so the rest of the app is still reached.
- `leaks > 0` in readonly mode: a write reached the server. Stop, show the user `leaks.jsonl`, and continue only after they confirm the app's data may change (then the run is `sandbox`).
- `counts.blocked` is the number of rejected writes (`blocked.jsonl` lines without `why: "selfcheck"`): crawler clicks the guard stopped from writing, and PUT/PATCH/DELETE the page tried while loading.
- The log shows the login page's heading and new states stop appearing: the session expired; redo step 2 and crawl again with the same `dataDir`.
- `counts.stopped` is set (the tab died, usually a page whose script froze it): the states before it are complete on disk; keep them and go on with step 5. Do not move or delete the `.data`/`.media` directories to retry; a retry needs a fresh `browser.open` and a new stem.

The passive writes (step 3), grouped by procedure (method + URL path; for tRPC the path names the procedure):

```js
const passive = (await Bun.file(`${dataDir}/passive.jsonl`).text()).split('\n').filter(Boolean).map((l) => JSON.parse(l))
  .filter((r) => r.why === 'passive');
const procs = Object.entries(Object.groupBy(passive, (r) => `${r.method} ${new URL(r.url, url).pathname}`))
  .map(([k, v]) => `${k} ×${v.length}`);
```

Then close the crawl tab: `await browser.close({ name: 'explore' })`. Steps 5-7 need no tab; a tab opened later (a redo of step 2, a check in step 8) is closed with `browser.close({ name })` at the end of the step that opened it.

**Done when** every same-origin link in the main navigation of `s01` (header, sidebar or nav bar on `s01.som.png`) leads to a state in `graph.json`, every state has its `.png`, `.som.png` and `screens/<id>.json`, the `explore` tab is closed, and in readonly mode the chat shows the user `counts.blocked` and the distinct passive write procedures `procs` (method + path, count), or "no passive writes".

## 5. Perceive every screen

Models perceive, rules decide. `rubric.json` beside this file is the single source of the per-screen questions, the synonym and first-click questions, the rules that turn answers into **findings** (rule id, severity 0–4 after Nielsen, report label), the confidence `gate`, the clarity weights and `bands`, and the `since` change thresholds; change a question or a threshold there, never in code. The model work lives in `pipeline.mjs`, imported like `crawl.mjs`; it gets the eval helpers passed in because module code cannot see them:

```js
const ap = await import(`${helpers}/pipeline.mjs`);
const p = await ap.perceive({ judgeBatch, completion }, { dataDir });
```

Two things run in parallel per state. The cheap judge answers the rubric questions (screen type, primary action, hierarchy, title, location, density, labels, icon-only) looking at `<id>.som.png`; the smol model reads the aria snapshot, visible text and marks and extracts the screen's `purpose`, the objects it shows (name, shown as, attributes, count) and its actions (verb, object, mark, primary). Both land in `<stem>.data/perceive.json` as `{<id>: {answers, extract}}`; `run.json` gets `perception: "judge"`.

`p.failed.judge` or `p.failed.extract` non-empty: run `perceive` once more (it rewrites every state). `p.judge_error` set means no image-capable judge exists on this machine and `run.json.perception` is `pending`; then the critic agents answer instead:

1. Split the state ids into batches of 10. Per batch one `agent(prompt, { agent: 'app-explore-critic' })`, all in parallel, prompt: read `rubric.json` `questions`; for each listed state read `<stem>.media/<id>.som.png`; answer every question in the judge's answer shape (`choice` → `{choice, probabilities: {label: p}, confidence}`, `bool` → `{bool: P(yes)}`, `score` → `{score, probabilities: {"0": p, …}, confidence}` with `score` the probability-weighted level), stating honest probabilities; write `{<id>: {<question id>: answer}}` to `<stem>.data/perceive.agent/<batch>.json`; return only the file path.
2. `const missing = await ap.mergeAgentAnswers({ dataDir })` merges them and sets `perception: "agent"`; re-run the batches holding `missing` ids.

**Done when** `perceive.json` has one entry per `graph.json` state, each with `answers` and `extract`, and `run.json.perception` is `judge` or `agent`.

## 5b. Saliency (feature `saliency` only)

Run this step only when `run.json.features.saliency` is true:

```bash
PY=$(bash <skill dir>/saliency/setup.sh) && "$PY" <skill dir>/saliency/run.py <reports dir>/<stem>.data <reports dir>/<stem>.media
```

`setup.sh` installs once into `~/.cache/app-explore/saliency/`: a python3.11 venv with TensorFlow, tf-keras and Pillow, and the UMSI++ weights `umsi++.hdf5`, downloaded from the UEyes site on the user's machine (the skill does not ship them). It prints the venv's python; later calls skip what exists. `run.py` predicts where a first look lands on each screenshot with UMSI++ (UEyes, CHI '23, trained on eye tracking over UI screenshots) and writes `<stem>.media/<id>.sal.png` (heatmap over the screenshot, the primary action outlined) and `<stem>.data/saliency.json` = `{<id>: {primary_mark, primary_source, primary_share, primary_rank, marks, top_marks: [{mark, share}], rendered_ms}}`. A mark's `share` is its attention per pixel against the page average (saliency mass in its box over the box's share of the page). The primary mark is the action `perceive.json` `extract` flags `primary`, else its first action with a mark.

`setup.sh` fails (exit 2: no python3.11; else pip or the download failed): record why and go on with step 6:

```bash
python3 <skill dir>/saliency/run.py <reports dir>/<stem>.data <reports dir>/<stem>.media --error "<setup.sh's last stderr line>"
```

`run.py` records its own failures the same way. `run.json.saliency_error` reaches the report's `run_details`.

**Done when** `saliency.json` has an entry per `graph.json` state and each has its `<id>.sal.png`, or `run.json.saliency_error` is set.

## 6. Synthesise the object model, check synonyms and first-click scent

```js
const m = await ap.synthesize({ completion }, { dataDir });
const y = await ap.synonyms({ judgeBatch }, { dataDir });
const s = await ap.scent({ judgeBatch }, { dataDir });
const sp = await ap.pathScent({ judgeBatch }, { dataDir });   // after scent; feature scent_path off: { skipped: true }
```

`synthesize` hands every extraction plus the graph (state id, route, heading, depth, edges) to the slow model once and writes `<stem>.data/model.json`: 2 **personas** (`p1` first-time user, `p2` a domain role), the **objects** in OOUX terms (one object per thing, every other UI name of it in `aliases`; class core, supporting, child or system; attributes, relationships, calls to action, home states, representations) and at most 6 **tasks** (create, find, edit of core objects, each with a `target_state`). Objects whose `homes` hold no `graph.json` state and new tasks whose `target_state` is missing are dropped (`m.dropped` counts them). Names are in the app's language (`run.json.lang`). With feature `personas` n > 1 every persona also gets n-1 **variants** in the same call: other people in the same role, spread over digital literacy, hurry and prior domain knowledge (`{id: "<persona id>-v<k>", name, literacy, hurry, domain, note}`, value lists in rubric.json `personas`); `m.variants` counts them and `m.variants_short` lists personas that got fewer.

With `since`, `synthesize` reads the previous `model.json` and `graph.json` from `run.json.since` itself: persona and object ids stay the same for the same things, every previous task is kept as it was (up to 2 new ones join it), and its `target_state` is not the model's pick but the state of this crawl that matches its previous target the way `diff.json` matches screens (state key, else route + kind + heading). A previous task without such a match gets `target_state: null` and `target_missing: true`, so step 8 walks it and it fails visibly. `model.json` `kept` = `{ids, missing}` (the previous task ids, and those without a target); `synthesize` returns the same `kept`.

`synonyms` lets the cheap judge check what the naming rule would otherwise take on the slow model's word: per candidate pair "do both labels name the same thing?" (rubric.json `synonyms`, gated like every bool). Candidates, capped at `synonyms.max_pairs`: each object's name against each of its `aliases`, object names that share a word, and object names the per-screen extraction used that are no model name or alias against the object names they share a word with. `<stem>.data/synonyms.json` lists the pairs with their `answer`; `analyze.py` drops an alias judged a different thing, adds a screen label judged the same, and merges two objects judged one thing into one naming finding; undecided pairs go to `needs_check.json`. `y.judge_error` set: the judge is unavailable, every answer is null and naming rests on the model alone; go on.

`scent` asks the judge, per task, which numbered mark on the entry state (the crawl's first state) the persona would click first, and compares it with the first edge of every shortest click path from there to the task's `target_state`. `<stem>.data/scent.json` per task: `predicted_mark`, `p`, `shortest_first_mark`, `first_marks`, `first_labels`, `clicks`, `correct` (`null` when the target is the entry itself, unreachable or `null`, or the judge gave no answer; `false` when the path's first control carries no mark on the entry screenshot, e.g. below the fold).

`pathScent` (feature `scent_path`) repeats the scent check on every state of each task's shortest path, the entry included, the way a user scans: the state's marks in reading order (rows top to bottom, left to right), cut into groups of `rubric.json` `scent.chunk_size` (8; at most `scent.max_marks` marks). The judge sees one group at a time with the persona, the task, the step and the clicks so far, and picks one of the group's marks or `next`; `next` shows the following group in the next round. It adds `steps[]` to each task in `scent.json`: per path state `step` (0 = entry), `state`, `chunk` (group of the pick, 1-based), `chunks`, `predicted` (mark; `null` = nothing on this screen), `expected` (the path's marks), `expected_chunk`, `correct` (as for the entry), `premature` (wrong pick in a group before the right mark's group), `p`. Every call is a judge call of kind `path_scent`. `sp.judge_error` set: the judge died; the unanswered steps carry `error: "judge unavailable"`; rerun `pathScent` once the judge is back.

- `m.objects < 3`: the crawl saw too little of the app; go back to step 4 with a higher budget.
- `scent` throws `judge unavailable`: one `app-explore-critic` agent reads `scent.questions.json` and its `image`, answers `first_click` per task in the judge choice shape into `<stem>.data/scent.agent.json`; then `await ap.scent({ judgeBatch }, { dataDir, answers: JSON.parse(await Bun.file(`${dataDir}/scent.agent.json`).text()) })`.

**Done when** `model.json` has ≥ 3 objects, each with a `homes` state in `graph.json`, every task's `target_state` exists in `graph.json` (with since: or is `null` with `target_missing`), `synonyms.json` exists, `scent.json` has one entry per task (with `scent_path`: each with `steps[]`, one per path state), and `run.json.models` has `calls` for `perceive_judge`, `extract`, `synthesize`, `synonyms` (when it had pairs), `scent` (when the judge answered) and `path_scent` (with `scent_path`, when a task has a path).

## 6b. Mental model (feature `mental_model` only)

A simulated first-time user knows only what it has seen. `mentalModel` replays the crawl edges in BFS order from the entry state, at most `rubric.json` `mental.max_edges`; per edge three cheap calls: `smol` predicts from the model so far and the clicked label what the click will show (kind, heading, object, purpose; `mental_predict`), the judge decides `matches` between that prediction and the target state's screenshot plus perceive extract (`mental_match`, gated like every bool; undecided = `null`), and `smol` updates the **concepts** (objects, places, actions with `believed_attributes`, `seen_in`, `confidence`) and logs **contradictions** (`mental_update`). Feature off: it returns `{ skipped }` and writes nothing.

```js
const mm = await ap.mentalModel({ judgeBatch, completion }, { dataDir });   // { edges, of, concepts, violations, unsure, errors }
```

`<stem>.data/mentalmodel.json` = `{cap, concepts, timeline, violations, after_crawl, errors?}`: `timeline[]` one entry per step (0 = the entry state) with `state`, `label`, `predicted`, `matches`, `p`, `added`/`confirmed`/`contradicted`, `concepts` (count so far) and the ids of its `violations`; `violations[]` with `id`, `kind`, `source` (`crawl` | `walk`), `state`, `label`, `expected`, `observed`. The four kinds: `expectation` (the click showed another thing than its label promised), `affordance` (the control looked like one kind of control and acted like another, e.g. a project link that only expands the sidebar), `location` (a known thing turned up where the user did not expect it), `naming` (`names`: one thing under two names, `same-object-different-name`, or one name for two things, `same-label-different-target`). A miss's kind comes from the update; contradictions on a step that already missed are dropped as repeats.

- `mm.errors > 0`: `mentalmodel.json` `errors` names the step and call kind; a judge outage leaves `matches: null` on those steps and adds no violation. Re-run this step once the judge answers; it rewrites the file.

**Done when** `mentalmodel.json` exists with one `timeline` entry per replayed edge plus the entry, `run.json.models` has `calls` for `mental_predict`, `mental_match` and `mental_update`, and `mm.errors` is 0; with `mental_model` off, no `mentalmodel.json` exists.

## 7. Findings and scores

```bash
python3 <skill dir>/analyze.py <reports dir>/<stem>.data            # with since: append  --since <since>
```

`analyze.py` (Python stdlib) applies `rubric.json` rules to the perceptions, the crawl's geometry (overflow, overlap, small targets), the object names (several labels for one object, OOUX P13, after the synonym checks of step 6), click depth from the entry state, `scent.json`, `leaks.jsonl` (readonly runs; a walk's leak names its task), and, once they exist, `walks/*.json` and `critique/*.json`. With `scent_path`, a task's `steps[]` replace its entry check: each wrong step gives `S-scent` on that step's screen (the text names the step), or `S-premature` when the pick came in an earlier group than the right mark. Every judge answer and critique finding passes the rubric.json `gate` (bool true/false thresholds, choice: the chosen label's own probability, critic confidence); a `score` counts as its expected level. Anything outside the gate never becomes a finding; it goes to `needs_check.json` ("needs a human look") with its leaning answer and the rules it would trigger.

It writes into the data dir:

- `findings.json`: one finding per rule and state, id `<rule>@<state key[:8]>` (stable across runs); a naming finding is one per object, id `<rule>@<state key[:8]>-<object id>`, with `object`; a walk finding is one per task, id `<rule>@<state key[:8]>-<task id>`, with `task`. Each has `source`, `sev`, `text`, `marks`, `confidence` and `pins` (`{x, y, n}` in percent at each mark's box centre, `{x: 4, y: 4}` without marks), sorted by severity. With feature `examples` a critic finding also has `box` (`{x, y, w, h}` in viewport percent; without marks its pin sits at the box centre) and `example_ids`.
- `scores.json`: `clarity` 0–100 per screen and for the app, `findability` (walk success rate × mean directness; `null` before walks; with feature `personas` the rate per task over all its walks), `naming` (share of objects with one name).
- `needs_check.json`, and the collections `screens.json`, `objects.json`, `tasks.json` for the report.
- Feature `seq` on: `W-friction` findings (source `seq`, one per state and task, id `W-friction@<8 hex>-<task id>`) on the state of every walk step rated SEQ ≤ `max_seq` or at least `min_drop` below the step before (rubric.json rule thresholds); `tasks.json` rows gain `seq` (per step, 1-7) and `sus` (0-100: 2.5 × Σ odd items x−1, even items 5−x; `null` without 10 valid answers); `scores.json` `app` gains `sus` (mean) and `sus_personas`; `diff.json.tasks` briefs carry `sus`. Off: none of these.
- Feature `personas` n > 1: a task's walks are its base walk `walks/<task>.json` plus its variant walks `walks/<task>-<variant>.json`. `W-failed` fires when the task's success rate is at most `max_rate`, else `W-struggle` when at least `min_share` of its walks failed or struggled (rubric.json rule thresholds); the finding carries `rate` and `walks`, names who failed and sits where the first of them ended. A task with one walk keeps the single-walk text. `W-friction` covers every walk. `tasks.json` rows gain `walks`, `successes`, `rate`, `rate_ci` (Wilson 95 % interval, z = rubric.json `personas.wilson_z`), `clicks_median`, `clicks_range`, `ease_median`, with `seq` also `sus_mean` and `sus_range`; `scores.json` SUS counts every walk; `diff.json.tasks` briefs carry `walks`, `rate`, `rate_ci` (and `sus_mean`). n = 1: variant files are ignored and every output is the single-walk one.
- Feature `saliency` on and `saliency.json` present: `R-salience` findings (source `saliency`, marked on the primary action) on each screen whose primary action ranks outside the top `top_frac` of its marks by `share`, or whose top mark has over `max_ratio` × the primary's `share` (rubric.json rule thresholds). Off: none.
- Feature `mental_model` on and `mentalmodel.json` present: one `M-expectation` finding (source `mental`, id `M-expectation@<8 hex>-<kind>`, `violations`: the violation ids, `tasks` for walk ones; severity per kind from rubric.json) per state and violation kind, on the state the click led to; a walk step that left the crawled graph lands on its task's `target_state`, else the entry, and the text names the URL. A `naming` violation whose two names already are one object's labels, or a pair `synonyms.json` judged two different things, adds nothing. Undecided crawl matches go to `needs_check.json`. Off: none.

With `--since` (the previous run's data dir) it also compares the two runs and writes `diff.json`: screens match by state key, else by route + kind + heading; a matched screen is **changed** past the rubric.json `since` thresholds (dHash bit distance, clarity delta, interactive-label Jaccard). `diff.json` = `{since, since_data, match: {<id>: <prev id>}, screens: {new, removed, changed: [{id, prev, dist, clarity_delta, jaccard}]}, objects: {new, removed, renamed}, tasks: {<id>: {prev, now}}, findings: {fixed, unverified, open, new}}`, and every finding in `findings.json` gets `status`: `open` when the same rule held on the matching previous screen (a walk finding: for the same task), else `new`. A previous finding that no longer fires is `fixed` only when this run looked again (its screen matched, or its task was walked again); on a screen this crawl did not reach it is `unverified`. It prints one `since` line with these counts.

Run it again after every later step that adds walks or critique; it rewrites all its outputs (with the same `--since`).

**Done when** the command prints its findings summary (and with `since` its `since` line), every `findings.json` id matches `<rule>@<8 hex>` (naming: `<rule>@<8 hex>-<object id>`), and no answer listed in `needs_check.json` produced a finding.

## 8. Walks and critique

Two kinds of evidence a screenshot cannot give: does a person reach the goal, and what does a careful reviewer see that the closed questions missed. Each task of `model.json` becomes a **walk**: an `app-explore-walker` agent plays the task's persona in its own hidden tab, thinks aloud before every click, and writes `walks/<task id>.json`. Then one `app-explore-critic` agent reviews the eight lowest-clarity screens against Nielsen's heuristics and writes `critique/c1.json`. Each agent's model comes from its agent definition (walker `@task_standard`, critic `@slow`); the `task` calls pass none. Everything this step runs in the kernel uses the cheap roles of `rubric.json` `models` (kernel walks: `walk_step`, `walk_survey` on `smol`). Both agents know their file formats; the prompts only carry the brief.

Walks run in waves with a barrier per wave: at most 2 at a time when the app is a local dev server (host `localhost` or `127.0.0.1`: every walker's full page load competes for the same dev server, and an unbundled one serves ~1500 modules per load), else 4. The walker gets the task's title, never its `target_state`: it must find the way like a user. With `since`, `model.tasks` already holds every previous task id plus the new ones (step 6), those whose screen is gone included, so the loop re-walks all of them; their results land in `diff.json.tasks` as `{prev, now}` after the re-run of `analyze.py`.

```js
const model = JSON.parse(await Bun.file(`${dataDir}/model.json`).text());
const run = JSON.parse(await Bun.file(`${dataDir}/run.json`).text());
const persona = (id) => model.personas.find((p) => p.id === id) || model.personas[0];
const brief = (t) => [
  `persona: ${JSON.stringify({ ...persona(t.persona), variants: undefined })}`,
  `task: ${JSON.stringify({ id: t.id, title: t.title })}`,
  `url: ${run.url}`, `mode: ${run.mode}`, `dataDir: ${dataDir}`, `helpers: ${helpers}`,
].join('\n');
const answers = {};
const perWave = /^(localhost|127\.0\.0\.1)$/.test(new URL(run.url).hostname) ? 2 : 4;
for (let i = 0; i < model.tasks.length; i += perWave) {
  const wave = model.tasks.slice(i, i + perWave);
  const hs = await Promise.all(wave.map((t) => agent(brief(t), { agent: 'app-explore-walker', label: `walk-${t.id}` })));
  const out = await wait(hs, { raiseErrors: false });
  wave.forEach((t, k) => { answers[t.id] = out[k]; });
}
```

A walker that answers `browser unavailable` (its eval kernel has no `browser`), or one that failed and left no `walks/<id>.json`, is re-run in this kernel, one task after the other. `walk.mjs` drives the same tab with one completion per step (role `walk_step`) over the mark list and the visible text, with the same 15-step limit, deny-list and write guard, and writes the same file (with `by: "kernel"`):

```js
const wk = await import(`${helpers}/walk.mjs`);
for (const t of model.tasks) {
  if (existsSync(`${dataDir}/walks/${t.id}.json`)) continue;
  await wk.walkInKernel({ ax, browser, completion, persona: persona(t.persona), task: t, url: run.url, mode: run.mode, dataDir });
}
```

With feature `personas` n > 1 the walker agent stays one per task; the other n-1 walkers of a task are its persona's `variants` (step 6), walked in this kernel by `walk.mjs` on `smol`, each playing its variant and writing `walks/<task id>-<variant id>.json` (with `variant`). `walkAll` runs them all, at most 2 at a time on a local app and 4 otherwise (rubric.json `personas.walk_concurrency`), and skips every walk whose file exists, so calling it again redoes only missing or deleted ones:

```js
const fan = await wk.walkAll({ ax, browser, completion, url: run.url, mode: run.mode, dataDir });   // n = 1: { walked: 0 }
```

`fan.errors` lists the walks that threw (`{task, variant, error}`); call `walkAll` once more for them.

Critique: the eight states with the lowest clarity in `scores.json` (from step 7), lowest first, in one critic call, batch `c1`. `criticBrief` writes the prompt: without `examples` the bare `dataDir`/`states`/`batch` brief; with it, also the picked example critiques and, per state, the ids of the four matched to the judge's `screen_type` answer. The UICrit examples come without their RICO screenshots: the critic reads their text and box as the description, and the brief needs no image.

```js
const scores = JSON.parse(await Bun.file(`${dataDir}/scores.json`).text());
const worst = Object.entries(scores.screens).sort((a, b) => a[1] - b[1]).slice(0, 8).map(([id]) => id);
const critic = await agent(await ap.criticBrief({ dataDir, states: worst, batch: 'c1' }), { agent: 'app-explore-critic', label: 'critic-c1' });
await critic.wait();
```

Then run `analyze.py` again exactly as in step 7 (with `--since <since>` when set): it turns failed and struggling walks into `W-failed` / `W-struggle` findings (a wrong turn is a step with `confused: true`; with feature `personas` on each task's success rate over all its walks), steep SEQ drops into `W-friction` (feature `seq`), the first-click check into `S-scent`, and the critique into `C-<n>` findings (feature `examples`: with their `box` and `example_ids`; a critic finding with neither a box nor a known mark goes to `needs_check.json`).

Read the walk answers as they come back. A walk that ended in `give-up` on the first screen with no marks usually means the page had not rendered or the session expired, not a usability problem: check `walks/<id>.json` `steps[0].url` and redo step 2 before believing it. A `W-failed` or `W-struggle` walk whose think-aloud (`steps[].think`, `survey.comment`) talks about loading, a blank or empty screen, a spinner or "taking too long" measured load time, not usability: delete its `walks/<id>.json`, redo that walk alone (one walker, no other walk running) and re-run `analyze.py` before believing it. Any new line in `leaks.jsonl` after the walks in readonly mode: stop and show it to the user, as in step 4. Recompute `procs` (step 4) after the walks: the walkers' passive writes land in `passive.jsonl` too.

**Done when** `walks/` has one file per task in `model.json` (each with `steps`, `success`, `clicks`, `survey`) and, with feature `personas` n > 1, one per task and variant of its persona (n-1 per task) after the second `walkAll` at the latest, no `W-failed`/`W-struggle` finding rests on a walk whose think-aloud blames loading, `critique/c1.json` is a JSON array of findings with `state`, `rule` `C-1`…`C-10`, `sev`, `marks` and `confidence` (feature `examples`: also `box` and `example_ids` on every finding), the re-run `findings.json` contains `W-*`, `S-scent` or `C-*` findings where the walks and critique gave reason, `leaks.jsonl` is empty in readonly mode, every tab this step opened in this kernel is closed, and in readonly mode the chat shows the user the distinct passive write procedures of the whole run (`procs`, method + path, count), or "no passive writes".

## 8b. Walks into the mental model (feature `mental_model` only)

The walks show what a user expected before each click (`expected`) and what happened (`outcome`). `mentalModel` with `pass: 'walks'` restarts from the crawl's model (`after_crawl`) and feeds the base walks in turn (`walks/<task>.json`; persona variants with a `variant` field are skipped, so the model stays one person's and the cap goes to the base walks), at most `mental.max_walk_steps` steps in all: an `as-expected` / `unexpected` outcome decides the match directly, the judge decides free-text outcomes (`mental_match`), `blocked` steps count for nothing, and one `smol` update per walk (`mental_update`) adds the walk's concepts and the kind of every miss. It keeps the crawl part of the timeline and violations and rewrites the walk part, so it is safe to repeat after a walk is redone.

```js
const mw = await ap.mentalModel({ judgeBatch, completion }, { dataDir, pass: 'walks' });   // { walks, steps, concepts, violations, walk_violations, errors }
```

Then run `analyze.py` again exactly as in step 7: walk violations become `M-expectation` findings with their task.

**Done when** `mentalmodel.json` has a `walks` entry (`fed` = the walk files with expectations), one `timeline` entry per fed walk (source `walk`), `mw.errors` is 0, and the re-run `findings.json` holds an `M-expectation` finding for every violation whose state or task resolves.

## 9. Report

Turn the run into report blocks:

```bash
python3 <skill dir>/compose.py <reports dir>/<stem>.data <reports dir>/<stem>.media
```

`compose.py` (Python stdlib) writes `<stem>.data/blocks.json` = `{entities, badges, stats, blocks}` and the collection `findings_serious.json` (sev ≥ 3) behind the serious-findings stat. Entities: objects `o-<id>` (home: an `objects_table` row), tasks `t-<id>` (a `tasks_table` row), screens `s-<id>` (a gallery item), findings `f-<rule>-<key>` (rows of the one `tree`, badge `sev`, three labelled `meta` lines `Where:` (linking screen, object, task), `Source:`, `Confidence:`, which the report renders as the tree's three headed columns; the finding text is in the `findings_data` table; an unlabelled meta line repeated on two rows would become a column of its own). Blocks, by name:

|Block|Type|Shows|
|---|---|---|
|`objects_table`|table|every object: class badge, how it is shown, other names, home screens, finding count|
|`naming_table`|table|objects shown under more than one name|
|`tasks_table`|table|every task: persona, object, target screen, shortest path, first click, walk result, clicks, ease; feature `seq`: SUS (with `since`: "now (was prev)"); feature `personas` n > 1: walk result as successes/walks with the 95 % interval ("2/3 (21-94 %)"), clicks as median (range), median ease, SUS as mean (range), with `since` the previous successes/walks and SUS as "now (was prev)"|
|`seq_tabs`|tabs|feature `seq` only: per walked task a `bars` chart of its steps' SEQ 1-7, red at or below the `W-friction` threshold|
|`cta_tabs`|tabs|per object its attributes, related objects and actions with their screens|
|`nav_map`|map|screens as boxes (dialogs and menus dotted), clicks as edges|
|`depth_bars`|bars|screens per click depth|
|`scent_table`|table|per task the predicted first click against the first click of the shortest path; with `scent_path` one row per path step (`Step` column), `too early` for `S-premature`|
|`mental_growth`|bars|feature `mental_model` only: concepts a first-time user knows after each crawl click and each walk, red where the step broke an expectation (its `p` says so)|
|`mental_table`|table|feature `mental_model` only: every violation with kind, crawl or task step, the screen it happened on (links to its gallery shot and pins) and its `M-expectation` finding|
|`scorecard_table`|table|per screen, least clear first: clarity and every rubric answer (`(?)` = under the confidence gate)|
|`rubric_bars`|bars|findings per rule, coloured by their worst severity|
|`findings_tree`|tree|every finding, filtered by severity|
|`findings_data`|data|every finding, sortable, with evidence and confidence|
|`screens_gallery`|gallery|one item per state in BFS order, badges screen type and clarity band, one numbered note per finding linking to its tree row|
|`saliency_gallery`|gallery|feature `saliency` only: one heatmap per scored state, caption the primary action's attention rank, notes its `R-salience` findings; a gallery of its own, so `screens_gallery`'s Before/Now toggle stays the `since` comparison|
|`needs_check_table`|table|answers too unsure to count: "needs a human look"|
|`status_table`|table|with `since` only: findings per severity fixed / still open / new / not re-checked, plus a total row|
|`run_details`|table|what the run used that the report must name: with feature `examples` and a critique, the critic's example bank and its UICrit attribution (CC BY 4.0); with feature `saliency`, the attention model and its sources, or `saliency_error`|

A block whose data is empty (no naming conflict, no task, nothing unsure) is not in `blocks.json`; its section says so in one sentence instead.

With `since` (`diff.json` exists) `blocks.json` is a change document: top-level `since` = the previous stem; gallery items carry `change: new` or `changed` (changed ones get `before` = the previous shot, so the lightbox shows a Before/Now toggle); every removed screen is appended to the gallery as a `removed` item (struck through) showing its previous shot `<prev stem>.media/<id>.png`, path relative to the report, with entity `s-was-<prev id>`; finding entities carry `change: new`, fixed findings return as `removed` tree rows; unverified findings stay out of the tree and only count in the status table's "not re-checked" column; `findings_data` gets a "since last run" column; `status_table` appears. The report renders the change bar with the counts of new, changed and removed parts (removed = removed screens + fixed findings); on an identical re-run (report ≥ 0.6.3) it says "none" and the status table shows every finding still open.

Then start one `task` subagent, the report skill's autopilot path; this session waits for it. Its task text, with the placeholders filled:

```
autopilot. Question: "How clearly does <host> present its objects, tasks and navigation?"
Read skill://report and follow it, steps 1-9. Stem <stem>, directory <reports dir>; the dump is <stem>.data/.
Profile app-audit, size detailed, mode autopilot, lang = run.json `lang`.
Write <stem>.choice.json exactly as:
{"profile": "app-audit", "size": "detailed", "mode": "autopilot", "features": ["none", "tree", "data", "charts", "map", "gallery"],
 "questions": [
  {"id": "q1", "chapter": "What exists", "text": "Which objects does a user perceive, and under which names?", "feature": "tree"},
  {"id": "q2", "chapter": "What exists", "text": "Which tasks can a user do, and do they succeed?", "feature": "tree"},
  {"id": "q3", "chapter": "How it is reached", "text": "How are screens and functions reached?", "feature": "map"},
  {"id": "q4", "chapter": "What is wrong", "text": "How visually clear is each screen?", "feature": "charts"},
  {"id": "q5", "chapter": "What is wrong", "text": "Which problems should be fixed first?", "feature": "data"},
  {"id": "q6", "chapter": "What is wrong", "text": "What does each screen look like, and where are its problems?", "feature": "gallery"}]}
(chapter and question text in the report language). With since, append before `]}`:
 , {"id": "q7", "chapter": "What changed", "text": "What changed since <prev stem>?", "feature": "tree"}
(status_table is a table, which --check-choice counts as the tree feature).
Take `entities`, `badges`, `stats` and, with since, `since` from <stem>.data/blocks.json into <stem>.json unchanged, and every block from its `blocks`
unchanged, by name, in this order; the prose (`p`, `callout`, `argument`) is yours. Every block follows a `p` that states what it shows and what it means.
- lede (no question): `callout` tone `answer` with the verdict, then `argument`: claim = the verdict, reasons = the three fixes
  that remove the most severe findings, each linking one finding [[f-…]], conclusion = what to do first.
- q1: objects_table, naming_table
- q2: tasks_table, seq_tabs, cta_tabs
- q3: nav_map, depth_bars, scent_table, mental_growth, mental_table
- q4: scorecard_table, rubric_bars, needs_check_table
- q5: findings_tree, findings_data
- q6: screens_gallery, saliency_gallery, run_details (its `p` says these are the run's sources)
- q7 (since only): status_table; its `p` names the screen counts (new, removed, changed) and finding counts (fixed, open, new,
  and unverified as "not re-checked": on screens this run did not reach, so neither fixed nor open)
  from <stem>.data/diff.json, and the tasks whose walk result or SUS changed (`diff.json.tasks`, prev against now).
A block missing from blocks.json: drop it and say in one sentence why (for example "no object goes by two names").
Evidence: quote walkers' think-aloud lines verbatim in quotes from <stem>.data/walks/<task>.json (`steps[].think`, `survey.comment`),
in q2 and in the fixes they support. App-wide scores come from scores.json `app` (clarity 0-100, findability and naming 0-1, SUS 0-100 when present; 68 is the published average).
Name each `stats` number once in prose. Never invent a screen, object, finding or number that is not in the data dir.
Build: python3 <report skill dir>/build.py <stem>.json <stem>.html --check-choice <stem>.choice.json --strict
Verify per report step 9, including the gallery checks: a thumbnail click opens #gl-dlg with its pins and notes, ←/→ moves,
Escape closes and focus returns, at 1280 px document.documentElement.scrollWidth <= 1280 (the findings tree included),
at 390 px one column and scrollWidth == 390; plus: a note's → link jumps to its finding row;
with since: a `changed` item's Before toggle swaps the image to the previous shot, and removed items show struck-through titles with their previous shots.
Return the verdict, the three fixes, the autopilot chat line and the step-9 results.
```

When it returns, `open <reports dir>/<stem>.html` and answer in chat: the verdict, the three fixes, the report as a Markdown link with an absolute `file://` URL, and the subagent's autopilot chat line.

**Done when** the build printed `lint: 0 findings` with `--check-choice` and `--strict`; the `screens_gallery` item count equals the state count of `graph.json` (plus `diff.json.screens.removed` with since); the lede names a verdict and three fixes; at least one walk think-aloud line is quoted; the subagent reports report step 9 passed, including the gallery checks and `scrollWidth <= 1280` at 1280 px; and the chat answer carries the file link.
