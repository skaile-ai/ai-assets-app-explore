# Feature map: brief for the feature-map agent

You fill `featuresets` and `features` in `<out dir>/app-model.merged.yaml`, the merged app-model/1 file (`<app-model dir>/references/format.md`; read it first). You edit those two lists and nothing else in the file, then loop on the check below. You write no other file.

## Inputs

- `<out dir>/app-model.merged.yaml`: terms (with `seen_in`), `axes.operations` (each `{op, seen_in}`), screens, tasks, and the docs roster's featuresets and features when docs was a source.
- `<repo>/_concept/05_features/featuresets.md` when it exists: its feature rows, `## Ideas` rows and `## Cut` lines.
- `<out dir>/compare.md`: what each source lacks; read it to see why a feature exists in one source only.

## Rules

- **A featureset** groups features by what a user is doing, not by the entity touched: a skaileup slug (`model.py slug`) and one `purpose` sentence. Keep every featureset already in the file with its id and purpose; add a new one only when no existing purpose fits, and never one holding a single feature when an existing one fits.
- **A feature** is one outcome a role achieves, at the level of verb + object ("a member creates, finds and edits a Task"), not one button. Its id is the skaileup feature slug: lowercase, `[a-z0-9-]`, at most 48 characters, verb-object or object noun (`manage-tasks`, `api-tokens`).
- **Keep every docs feature** (a feature already in the file) with its id, featureset and outcome; you only add its `terms`, `ops`, `screens`, `tasks` and `roles`.
- **Reuse roster slugs.** A feature that an `## Ideas` row or `## Cut` line of `featuresets.md` already names takes that slug and that row's featureset, so `propose` does not raise it twice.
- Fields per feature: `outcome` one line; `terms` the object terms it touches; `ops` `{term, op}` pairs, each an op the term's `axes.operations` lists; `screens` the screen ids where it happens; `tasks` the task ids it serves; `roles` role term ids (empty when the app has one role); `status: null` (render sets it); `grade: inferred` unless the docs roster names it (`extracted`).
- **Evidence:** at least one entry: the roster row or spec it came from (`_concept/05_features/featuresets.md:<line>`), else the strongest evidence ref of one of its ops, screens or tasks, copied from that entry.
- An op, screen or task may belong to several features; prefer one.

## Coverage and the loop

```sh
$PY <app-model dir>/model.py validate <out dir>/app-model.merged.yaml
$PY <app-model dir>/featuremap.py check <out dir>
```

`check` lists every gap and exits 1 while any exist:

- every op of every `kind: object`, `origin: user` term is in at least one feature's `ops`;
- every `kind: page` screen seen in code or app is in at least one feature's `screens`;
- every task is in at least one feature's `tasks`;
- every docs feature is still there, and every feature cites evidence, a task or an op.

Fix the gaps and run both commands again, at most 3 rounds. Gaps that remain after round 3 are not forced into a feature: `featuremap.py render` lists them under `## Uncovered`.

## Return

The last `check` output, and per new featureset one line with its purpose and why no existing one fit.
