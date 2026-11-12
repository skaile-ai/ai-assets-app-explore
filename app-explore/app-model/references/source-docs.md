# Docs source: brief for the docs extractor

You build `app-model.docs.yaml`: what the app's documentation says its objects, roles, relations, screens and tasks are, in the app-model/1 format (`<app-model dir>/references/format.md`; read it first). You write that one file and nothing else.

```sh
PY="uv run --quiet --with pyyaml==6.0.3 python3"
$PY <app-model dir>/import_concept.py <repo> <out dir>/app-model.docs.yaml   # deterministic start
$PY <app-model dir>/model.py slug "<label>"
$PY <app-model dir>/model.py validate <out dir>/app-model.docs.yaml
```

## Start

Run `import_concept.py` first. It reads the skaileup `_concept/` tree (glossary, featuresets roster, feature specs, screens) and writes every entry it finds with `grade: extracted`; its warnings name references it dropped. Never change or remove a value it wrote: you add entries, fill its empty lists and nulls (attributes, axes) and append evidence refs, and its entries keep their `grade`. Features come only from the roster's tables; `## Ideas` rows are not features.

## Add

Read, where present: `README.md`, `CONTEXT.md`, `GLOSSARY.md`, `APP-DESIGN.md` (§ Objects, § Language, § Navigation model), `docs/**/*.md` (skip changelogs, ADRs older than their superseding record, and vendored docs), `_concept/brief.md`, `_concept/10_blueprint/datamodel/model.yaml`, `_concept/04_journeys/stories.yaml`, `_concept/07_screens/shell.md`.

- **Terms.** A noun the docs describe as something users manage, a role, or a named event or state, that the import does not hold. `id = slug(label)` with the label in the UI language when the docs give the UI's words (nav labels, button texts), else in the docs' main language; the other language's words go into `aliases` with every synonym the docs use. When the imported glossary names a thing by another word than the app (a template's `task` for the app's "To-do"), add the app's term with the imported id in `aliases` and leave the imported term as it is. Add axes on objects only where the docs state them; null otherwise.
- **Data model.** Each entity of `model.yaml` maps to a term through its `glossary` field, else through `slug(display or entity name)`; an entity with no term becomes a new `kind: object` term. Its fields become `attributes` (`home: null`), skipping ids, hashes, foreign keys and timestamps. `m2o` fields become relations (`belongs-to`; the target's `has-many` in reverse only when the docs say so).
- **Stories.** Each story of `stories.yaml` becomes a task: `id` = the story id slugged, `title`, `role` = its actor's term id, `verb` and `term` from what the story does, `screens` from screens it names that exist in this file. Without `stories.yaml`, workflows the docs describe step by step (a user does X on Y) become tasks the same way, at most 10.
- **Screens.** Destinations the docs name (the shell's `## Navigation` list, `APP-DESIGN.md` § Objects homes) without a `07_screens` file become screens: `kind` as the docs describe it (`page` by default; `drawer`, `dialog`, `popover` or `tab` when the docs say so), their route when the docs give one, else null. Nav items become `navigation` edges from a screen `shell` (`kind: page`, `route: null`) only if you add that screen.
- **Relations** the docs state in prose ("a case belongs to a patient").

Each added entry has `grade: inferred` and evidence `path#heading` or `path:line`. Do not add features or featuresets; the import's roster is the docs' feature list.

## Finish

Write YAML per format.md § YAML rules: quote every value that is `yes`, `no`, `on`, `off`, `null`, `~`, or a date or number meant as text. Set `provenance.made_by: app-model/docs` and add the files you read to `inputs`. Run `model.py validate` and fix every reported line; return only when it prints `ok:`. Return the `ok:` line and the import's warnings you could not resolve.
