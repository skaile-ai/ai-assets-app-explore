---
name: experience-app-objects
description: Use when an existing app's information architecture has to be
  analysed and re-planned from its objects outward — models the nouns the app
  manages, gives every attribute one home, and derives the screens, editors,
  search and command palette that model implies. Triggers on 'object model for
  this app', 'where should this information live', 'OOUX analysis', 'restructure
  the app around its objects'.
metadata:
  version: 0.4.0
  publisher: skaile-ai
  requires: "app-model"
  stage: alpha
---

# experience-app-objects

Builds the object model an existing app *should* have, derives the screens and editors that
model implies, and compares that to what the code actually has. The model comes first and
the code is measured against it — top-down. It writes analysis and a plan into
`_concept/02_grounding/findings/experience-app-objects/` — created if the project has no
`_concept/` yet — and the model's decisions into the app's `APP-DESIGN.md` (§ Objects,
§ Language, proposals in § Open); it changes no application code.

The rules applied are `<app-model dir>/references/app-patterns.md` (`P1`–`P17`, and how findings are
recorded); the decision file and who writes which part of it is
`<app-model dir>/references/app-design.md`; where screens, editors and finders sit per stack, and how
citations are checked, is `<app-model dir>/references/ui-detection.md`. Read all three before step 1.

`<app-model dir>` is the `app-model` skill's directory, which holds the references this skill shares with
`experience-app-guideline` and `experience-app-interview`: the first of `~/.agents/skills/app-model`,
`~/.claude/skills/app-model` and `~/.omp/agent/skills/app-model` that holds `references/app-patterns.md`.

**Questions.** A step that asks the user collects its questions into one round, each with a
recommended answer. When nobody can answer, write them to `questions.md` in the output
directory, proceed on the recommended answers, and tag every decision that rests on one
`[Q#]` — a different answer later is then a search, not a re-run. In `APP-DESIGN.md` such
a decision carries `[open Q#]`; `experience-app-interview` settles them with the user later.

**Subagents.** Legwork that only collects evidence — the attribute and representation
passes per object (steps 3 and 8), the button scan — runs faster in parallel subagents on a
small, fast model (Claude Haiku or Sonnet; pick it when spawning, the default model is
slower). Brief each with the ui-detection patterns it needs and the citation rule: paths
from the repository root, a bare file name is a failed citation. The button scan needs an
agent with a shell. They return `file:line` lists and write nothing; naming objects,
settling homes and judging gaps stay in the main session, which runs the citation check on
their lists before using them.

## Steps

1. **Fix the target.** Confirm the app root and detect the stack; a monorepo with several
   apps is a question, not a guess. Read `APP-DESIGN.md` if it exists, then the repo's
   glossary and ADRs (ui-detection § Intent): its decided homes, surfaces and exceptions are
   input to the model, and a model that contradicts one is a step-6 question. Where
   `_concept/02_grounding/findings/` holds `routes.md`, `screens.md` or `datamodel.md` from
   `concept-reverse`, verify those against the code instead of re-deriving; without them,
   derive from code. Where `findings/app-model/app-model.merged.yaml` exists (the
   `app-model` skill) and its `provenance.source_sha` equals `git rev-parse HEAD`, it is the
   starting object set for steps 2–4: its `kind: object` terms with their class, attributes
   (each `home`), relations, `axes.operations` and `seen_in`. Verify each against the code
   like the `concept-reverse` files instead of deriving it; the code wins where they
   disagree. From its `compare.yaml`: each `MM-name` row is a P13 finding citing the row's
   evidence, each `MM-only-code` row (`fix-ui`) a P8/P12 candidate gap.

2. **Extract the objects.** List every noun the app manages from the schema, the shared
   types and the API, then the labels the UI uses for them. A noun is an object when it has
   its own list, its own lifecycle or its own deletion; otherwise it is an attribute group
   or an enum. Objects the UI shows but no table stores are *derived* objects. Give each its
   class from app-patterns (`core`, `supporting`, `child`, `junction`, `system`); a type with
   its own nav entry and index is `core`. Record the schema name beside every UI label that
   differs: each difference is a P13 finding.

3. **Map attributes to owners.** For each object list its attributes, each with type, owner
   and the screen that is its canonical home today (P1). `none` and `several` are answers
   to write down — they are where this skill's sharpest findings come from. Attributes of a
   relationship go on a junction object; promote the junction to an object when it carries
   more than one.

4. **Map relationships and actions.** Relationships as a list of non-empty pairs only:
   `A shows B as <representation> (n)` (P2). Then a CTA matrix: per object, the actions it
   offers (create, edit, assign, archive…), who may trigger each — one column per role, or
   one line saying the app has one role — and where each is triggered in code. Search,
   palette and navigation are derived from these tables in step 7, so an action missing
   here is missing from the palette later.

5. **Derive the target screens and editors.** Per core object one row: index (P8), canonical
   home, the one editor (P4), the surface for each editing task by the ladder (P5) as a
   `task → surface` list, create flow (P6), delete confirmation (P7), representations
   (P2). Per supporting, child or junction object: its representation inside the parent and
   its editing surface there. `system` objects get their read-only representation only.

6. **Settle the model with the user.** Put the object table, the class calls and the
   contested canonical homes to the user as one round — at most eight questions, those
   that change a plan step first. The model is the input to everything after this step;
   changing it after the plan is written means writing the plan twice.

7. **Derive the finders and the navigation.** Search scope = the core objects (P9); palette
   = the CTA matrix ranked by context (P10); one action registry feeding buttons, menus,
   palette and shortcuts (P11); primary navigation = core indexes plus the cross-object
   workspaces with a task of their own (P12). Note what the code has today for each.

8. **Diff target against actual.** Homes (P1) and redundancy (P3) are step 3's answers —
   a `none` or `several` there is the gap, not re-checked here. Per object, answer against
   the code: representations (P2), editor count (P4), surfaces and create/delete flows
   (P5–P7), index count (P8), presence in search, palette and registry (P9–P11), names
   (P13). Where ui-detection has a grep, answer by grep and read the hits; P2 and P5 have
   none and are answered by reading the object's hosts — name the files read, so an unread
   host shows as unread. Saving, messages, popups and buttons (P14–P17) are app-wide: check
   them only when § Changelog has no `experience-app-guideline` run, otherwise cite its findings.
   Judge against `APP-DESIGN.md` where it decides a question, against the rule otherwise.
   Record each gap per app-patterns § Recording findings, with `file:line` evidence. A gap
   without a citation is an opinion: drop it or find the file.

9. **Write the artifacts.** Into the output directory:
   - `object-model.md` — objects, attribute ownership, relationship list, CTA matrix, the
     step-5 table;
   - `plan.md` — the gap register, then ordered changes, each a vertical change through one
     object (model → editor → surfaces → finders) citing the gaps it closes, with risk.
     Unblockers first, then user-visible payoff over effort. End with a coverage table:
     every gap maps to a change or is `accepted`.
   Into `APP-DESIGN.md`, per app-design § Writing it: § Objects (the step-5 rows,
   representations with their field subsets, the editor contract), § Language (one noun
   per object, from step 2), accepted deviations in § Exceptions, and every decision the
   model implies outside those sections — search scope, palette, surfaces — as a proposal
   in § Open. Run the citation check from ui-detection § Verifying citations over every
   artifact, `APP-DESIGN.md` included.

**Done when** every object's attributes each have one home in `object-model.md`, every core
object has a row in `APP-DESIGN.md` § Objects, every gap cites a rule id and a `file:line`
the citation check passes, every gap is covered by a change or accepted, and the step-6
questions are answered or open in § Open.
