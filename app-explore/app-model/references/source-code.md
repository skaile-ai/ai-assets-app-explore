# Code source: brief for the code extractor

You build `app-model.code.yaml`: the app's objects, roles, relations, screens, navigation and tasks as its code has them, in the app-model/1 format (`<app-model dir>/references/format.md`; read it first). You write that one file and nothing else.

```sh
PY="uv run --quiet --with pyyaml==6.0.3 python3"
$PY <app-model dir>/model.py slug "<UI label>"            # the id rule
$PY <app-model dir>/model.py validate <out dir>/app-model.code.yaml
```

## Inputs

The orchestrator gives you the repo root, the output dir and `<app-model dir>`.

1. **Findings first.** When `_concept/02_grounding/findings/{routes,screens,datamodel}.md` exist and their frontmatter `source_sha` equals `git rev-parse HEAD`, read them and verify each entry you take against the code (open the cited file). Otherwise derive everything from the code.
2. **Code.** Use the greps per stack in `<app-model dir>/references/ui-detection.md` (§ Screens, § Objects, § Editors and surfaces, § Finders, § Generated and vendored code):
   - the schema and ORM models (`server/db/schema/`, `prisma/schema.prisma`, `models.py`, migrations as a last resort);
   - shared types and the API (`shared/`, `types/`, server actions, route handlers);
   - routes and pages (`app/pages/`, `pages/`, `app/**/page.tsx`, router config), including those in layers or packages the app mounts;
   - navigation components (sidebar, nav, menu, command palette);
   - the page components, for what each shows and which actions it offers.
3. **UI labels.** The words users see come from templates, i18n files and nav labels, not identifiers.

## What to write

- **Object test** (experience-app-objects step 2): a noun is an object when it has its own list, its own lifecycle or its own deletion; otherwise it is an attribute group or an enum and does not get a term. Objects the UI shows but no table stores are derived (`axes.origin: derived`).
- **Terms.** `id = slug(UI label)`; when the UI language differs from the code's (English nav labels over German table names), the UI label wins and every code name goes into `aliases`. When the code name (table, model, type) differs from the UI label, put the code name into `aliases`. Roles (user roles, permission groups, API audiences) are `kind: role` terms. Enums named aloud as states are `kind: state` only when users see them by name and the name is unique among terms; otherwise they stay `status` attributes.
- **class** from app-patterns P1 (`core` has its own nav entry and index screen; `supporting`; `child`; `junction` for a join table carrying data; `system` for generated records).
- **axes** on every object:
  - `navigation`: `primary` when an entry of the app's main navigation (sidebar, top bar) leads to its index, `contextual` when reached through a parent, a settings sub-navigation or the user menu, `none` otherwise;
  - `lifecycle`: `owned-by:<parent id>` when a cascade delete or required parent FK ties it to a parent (add the parent as a `system` object when it has no term yet), `link` for a junction, else `independent`;
  - `origin`: `user`, `system` (written by jobs, imports, the app itself; read-only to users) or `derived`;
  - `operations`: the operations the code offers users, each backed by a handler, action or API route you cite; a soft delete that keeps the row (revoke, deactivate) is `archive`.
- **attributes**: user-relevant fields only (no ids, hashes, foreign keys, timestamps unless shown), each with `home` = the screen id where it is edited or shown primarily, `several`, `none` or null when unknown.
- **relations**: from foreign keys and joins: `has-many`, `belongs-to`, `owned-by`, or a verb phrase the code names.
- **screens**: one per routed page (`kind: page`, `route` as the router has it, `[id]` segments kept) and per dialog or drawer with its own component when it is an editor or a create flow. A page's `id` is the slug of its route with each parameter kept as its bare name (`/faelle/[id]/dokument` → `faelle-id-dokument`), `index` for `/`; a dialog's or drawer's `id` is the slug of its component name (`FallFormModal` → `fall-form-modal`), or the page id plus a suffix when it is written inside the page (`settings-tokens-create`). Ids must match `^[a-z][a-z0-9-]{1,47}$`. `shows` = the objects it lists (`row`, `card`, `chip`) or is the page of (`page`, `peek`). `actions` = the buttons and menu items with their verb, term and target screen.
- **navigation**: edges from the nav components (`label` = the nav label) and from links between pages you read.
- **tasks**: leave empty unless the code names user tasks (onboarding checklists, guided flows).
- **featuresets, features**: empty.

## Evidence and grade

Every term, relation, screen and task carries `evidence` with `path/from/repo/root:line` refs; a bare file name is a failed citation. `grade` is per entry: `extracted` when every value of it is read verbatim at its cited lines (a table name, a route path, a nav label), `inferred` when any value was concluded (a class, an axis, a relation read from a join). Set `provenance.source_sha` to `git -C <repo> rev-parse HEAD`, `made_by: app-model/code`, `inputs` to the globs and files you read.

## Finish

Write YAML per format.md § YAML rules: quote every value that is `yes`, `no`, `on`, `off`, `null`, `~`, or a date or number meant as text. Run `model.py validate` and fix every reported line; return only when it prints `ok:`. Return the `ok:` line and a list of nouns you rejected by the object test, each with its reason.
