---
name: app-model
description: Build one ontology of an app (objects, roles, relations, screens,
  tasks, features) from its code, its docs and the running app, compare the
  sources and list what does not fit, then derive a feature map and propose it
  into a skaileup _concept/ tree. Use for 'model this app', 'compare code and
  docs and app', 'what does the app have that the docs do not', 'feature map of
  this app', 'which features are hidden or unbuilt'.
license: MIT
metadata:
  version: 0.1.0
  publisher: skaile-ai
  requires: "app-explore"
---

# app-model [<repo path>] [url <url>] [from <code,docs,app>] [explore <stem>.data] [map] [propose]

You build `app-model.<source>.yaml` files, one per source, in one shared format (app-model/1, skaileup's vocabulary), align their terms, merge them into `app-model.merged.yaml`, and write a mismatch register `compare.md`. With `map` you derive a feature map from the merged model; with `propose` you append what it found as proposals to the repo's `_concept/` tree.

Read `references/format.md` before step 1. The scripts beside this file do the deterministic work:

|script|does|
|---|---|
|`model.py`|`validate <file>`, `slug "<text>"`, `json <file>`|
|`from_explore.py`|app source from an app-explore data dir|
|`import_concept.py`|docs source, deterministic part: the `_concept/` tree|
|`compare.py`|`candidates <dir>`, `run <dir>`: align, merge, mismatch rules|
|`featuremap.py`|`check <dir>`, `render <dir>`, `propose <dir> <repo>`|

**Paths.** `<app-model dir>` is this skill's directory: the first of `~/.agents/skills/app-model`, `~/.claude/skills/app-model` and `~/.omp/agent/skills/app-model` that holds `model.py`. Every script needs PyYAML; run them as:

```sh
PY="uv run --quiet --with pyyaml==6.0.3 python3"     # uv: ~/.local/bin/uv
$PY <app-model dir>/model.py validate <file>
```

Without `uv`: use `PY=python3` when `python3 -c 'import yaml'` succeeds; otherwise stop with `app-model needs uv or PyYAML: install uv (https://docs.astral.sh/uv/) or run pip install pyyaml`.

## 1. Inputs and sources

- **Repo**: the argument, else `git rev-parse --show-toplevel` of the cwd, else none.
- **Out dir**: `<repo>/_concept/02_grounding/findings/app-model/`; without a repo `~/.scratch/app-model/<host>/` (`<host>` of `url`). Create it.
- **Sources**: `from <list>` when given; otherwise `code` when there is a repo, `docs` when the repo has `README.md`, `docs/` or `_concept/`, `app` when `url` or `explore` is given.

Extract the sources in parallel:

- **code**: one `task` subagent with the brief `<app-model dir>/references/source-code.md`, given the repo, the out dir and `<app-model dir>`. It writes `app-model.code.yaml`.
- **docs**: one `task` subagent with the brief `<app-model dir>/references/source-docs.md`, same inputs. It writes `app-model.docs.yaml`.
- **app** with `explore <dir>`: `$PY <app-model dir>/from_explore.py <dir> <out dir>/app-model.app.yaml --repo <repo>` (omit `--repo` without one).
- **app** with `url`: run the `app-explore` skill on the URL, adding `seed <out dir>/app-model.docs.yaml` when docs is a source (start it after the docs agent returns, so the seed exists), then `from_explore.py` on its `<stem>.data` dir. The crawl is readonly; when real personal data shows on screen, stop the app run and say so.

**Done when** every requested source file exists.

## 2. Validate

Run `$PY <app-model dir>/model.py validate` on each source file. A failing file goes back to its agent once, with the error lines (`write agent://<id>`, or a new task with the same brief and the errors). Fails again: stop and show the user the errors.

**Done when** every source file prints `ok:`.

## 3. Align and compare

```sh
$PY <app-model dir>/compare.py candidates <out dir>      # YAML list {a, b, why}
```

Terms group automatically across sources when their slug sets `{id, slug(label), slug(alias)…}` intersect, except a `kind: role` term and a non-role term, which only a `same` pair joins. Each candidate pair is two terms in different groups that share a word of 3+ letters (function words such as `for`, `und` excluded) or look alike. Decide every pair yourself, reading both terms' labels, definitions and evidence in the source files: the same thing goes under `same`, different things under `different`, in `<out dir>/align.yaml`:

```yaml
same:
  - [code:fall, docs:case]
different:
  - [docs:user, app:user-account]
```

A `different` pair also splits an automatic group (two terms that share a word by accident). Then:

```sh
$PY <app-model dir>/compare.py candidates <out dir>      # must print []
$PY <app-model dir>/compare.py run <out dir>
```

`run` writes `app-model.merged.yaml`, `compare.yaml` and `compare.md`. With one source it writes only the merged file and prints `compare: one source, nothing to compare`.

### Compare

**Merge precedence.** The merged id is the docs id, else code, else app. `label`: docs > app > code. `class`, `axes.lifecycle`, `axes.origin`: code > docs > app. `axes.navigation`: app > code > docs. `operations` and `attributes`: union, each with `seen_in`. Screens align on the normalised route (`:id`, `[id]`, `{id}` and numeric segments become `*`); only `kind: page` screens are compared. Tasks align on their id (an app run with `seed` keeps the docs task ids): docs fields win, screens and evidence are the union. A rule runs only between sources that are present.

|rule|condition (object/role terms unless noted)|sev|suggestion|
|---|---|---|---|
|`MM-only-code`|object in code, no aligned app term|high if `class: core`, else medium|`fix-ui`|
|`MM-only-app`|object in app, no aligned code term|medium|`decide`|
|`MM-only-docs`|object in docs, in neither code nor app|medium|`decide`|
|`MM-undocumented`|object in code or app, docs present, not in docs|low|`fix-docs`|
|`MM-name`|aligned group with ≥2 different `slug(label)`|medium|`decide`|
|`MM-class`|non-null `class` differs|medium|`decide`|
|`MM-navigation`|non-null `axes.navigation` differs|medium|`decide`|
|`MM-operation`|op in code, not app: medium `fix-ui`; in app, not code: low `decide`; in docs, not code: medium `decide` (only where both sources hold the term)|—|—|
|`MM-relation`|a term pair related in one source, not in another that holds both terms|low|`decide`|
|`MM-screen-unreached`|code page route with no app page on the same normalised route; `confidence: low` when the crawl hit its state budget|medium|`fix-ui`|
|`MM-screen-unknown`|app page route matching no code route|low|`decide`|
|`MM-task-unreachable`|docs task the app walked (same id) without a target screen; else a docs task or feature whose `screens` match no app screen|medium|`fix-ui`|

`compare.yaml` = `{sources, undecided, mismatches: [{id, rule, subject, sev, confidence, suggestion, text, values: {<source>: value}, evidence: {<source>: [refs]}}]}`. `compare.md` has the source counts, the counts per rule, the register sorted by sev, rule, id, and `## Undecided pairs`.

**Done when** `compare.md` exists and `compare.yaml` `undecided` is empty.

## 4. Present

Show the user the counts per rule and the high and medium rows of the register (id, subject, the values per source, suggestion), and link `compare.md` as a Markdown `file://` link. `fix-ui` rows are work on the app, `fix-docs` rows work on the docs, `decide` rows questions for the owner: `experience-app-interview` puts them on its agenda.

## 5. Feature map (`map`, `propose`)

Only with `map` or `propose`. One `task` subagent fills `featuresets` and `features` in `<out dir>/app-model.merged.yaml` by the rules in `<app-model dir>/references/feature-map.md` and loops on `featuremap.py check` as that file says. Then:

```sh
$PY <app-model dir>/featuremap.py render <out dir>            # status per feature, feature-map.md
$PY <app-model dir>/featuremap.py propose <out dir> <repo>    # only with propose
```

`propose` appends `## Ideas` rows to `_concept/05_features/featuresets.md` for features no row covers, and `proposed` terms to `_concept/glossary.md` (concept mode) or to `<out dir>/proposals.md` (split mode) for merged terms the glossary lacks; it never edits an existing row or term. Show the user the status counts and what was proposed, with links to `feature-map.md` and the changed files.

**Done when** `featuremap.py check` exits 0 or `feature-map.md` lists the rest under `## Uncovered`, `feature-map.md` has every featureset heading and a status count table, and with `propose` the `_concept/` diff holds only appended lines.

## Done when

Every requested source file validates, `compare.md` exists, `undecided` is empty, and step 5 is done when `map` or `propose` was given.
