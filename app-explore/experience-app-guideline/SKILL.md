---
name: experience-app-guideline
description: Use when an existing app needs written interaction decisions —
  where information lives, one editor per type, inline vs modal vs page, saving,
  messages, popups, buttons, global search, command palette — and the code
  checked against them. Adopts a fixed rulebook, decides it per object type into
  the app's APP-DESIGN.md, then reviews conformance. Triggers on 'write an app
  guideline', 'APP-DESIGN.md', 'UI rules for this app', 'when do we use a
  modal', 'check the app against our patterns'.
metadata:
  version: 0.4.0
  publisher: skaile-ai
  requires: "app-model"
  stage: alpha
---

# experience-app-guideline

Rulebook first: adopts the rules in `<app-model dir>/references/app-patterns.md` (`P1`–`P17`), turns them
into this app's decisions globally and per object type, then checks the code for
conformance — the way a design system's floorplans are applied to a product. The decisions
are the main deliverable and go into `APP-DESIGN.md` at the app root, whose writer of record
this skill is (`<app-model dir>/references/app-design.md`). Findings, plan and questions go into
`_concept/02_grounding/findings/experience-app-guideline/` — created if the project has no
`_concept/` yet. No application code changes.

Where screens, editors and finders sit per stack, and how citations are checked, is
`<app-model dir>/references/ui-detection.md`; read it and `<app-model dir>/references/app-design.md` before step 1.

`<app-model dir>` is the `app-model` skill's directory, which holds the references this skill shares with
`experience-app-objects` and `experience-app-interview`: the first of `~/.agents/skills/app-model`,
`~/.claude/skills/app-model` and `~/.omp/agent/skills/app-model` that holds `references/app-patterns.md`.

**Questions.** A step that asks the user collects its questions into one round, each with a
recommended answer. When nobody can answer, write them to `questions.md` in the output
directory, proceed on the recommended answers, and tag every decision that rests on one
`[Q#]` — in `APP-DESIGN.md` as `[open Q#]` (app-design § Writing it); `experience-app-interview`
settles them with the user later. Without a user, step 9 reduces to the § Changelog line
and the final summary.

**Subagents.** Legwork that only collects evidence — the step-7 surface census, the button
scan, one grep pass per area — runs faster in parallel subagents on a small, fast model
(Claude Haiku or Sonnet; pick it when spawning, the default model is slower). Brief each
with the ui-detection patterns it needs and the citation rule: paths from the repository
root, a bare file name is a failed citation. The button scan needs an agent with a shell.
They return `file:line` lists and write nothing; classifying, deciding and judging stay in
the main session, which runs the citation check on their lists before using them.

## Steps

1. **Fix the target.** Confirm the app root and detect the stack; a monorepo with several
   apps is a question, not a guess. Read `APP-DESIGN.md` if it exists, the README, glossary
   and ADRs (ui-detection § Intent), the nav component and the layout: the decisions are
   written for the people who maintain this app, in their vocabulary. Decided entries and
   exceptions of an existing file are settled — later steps draft only what it lacks.

2. **Classify the object types.** List the types the app manages (schema, shared types,
   API) with: class from app-patterns (`core`, `supporting`, `child`, `junction`,
   `system`); for core and supporting types `simple` (one page of fields) or `complex`
   (sections, child collections); approximate field count; editing roles, or one line when
   the app has one role. `system` types users only read are listed once, by name, and leave
   the later tables; those users act on (assign, file, delete) keep their row.

3. **Decide the global rules.** For each of P1–P17: `adopt`, `adapt` (with the adapted
   wording) or `reject`, each with a one-line reason grounded in this app — its size, users,
   the stack's components. Example: P10 in a ten-screen app becomes "search is a mode of the
   palette". An adaptation keeps the rule's obligation and changes its form; one that
   removes the obligation is a `reject` and is written as one.

4. **Decide each type's floorplan.** Per type, one row: index (P8) · canonical home (P1) ·
   editor component, existing or to extract (P4) · create flow (P6) · delete confirmation
   (P7) · representations with their field subsets (P2) · in search? (P9). Under the table,
   per type, the editing tasks as `task → surface` (P5) and its palette actions (P10).
   Prefer what the code already does wherever it passes the rule — rename and fix, not
   redesign. Mark every cell `as-is` or `change`.

5. **Settle the contested decisions.** Steps 2–4 are drafts until this round. Ask the
   decisions a reasonable maintainer could make the other way — at most eight, those that
   change a plan step first; core/supporting calls usually lead. Apply the answers to the
   drafts before writing.

6. **Write `APP-DESIGN.md`** in the shape of app-design § Shape, updating an existing file
   in place. The step-3 decisions become entries in their area, imperative enough to apply
   in a pull request without this skill; the step-4 floorplans and representations go to
   § Objects; the contracts the rules imply sit in the entries that own them (app-design
   § Entries) — the editor shape under OBJ, the action registry entry under BTN. An adapted
   rule stays in its entry as `*Rules:* Pn adapt`; a rejected rule or accepted deviation
   goes to § Exceptions only on the user's answer, otherwise to § Open as `keep as
   exception?`. Each entry gets an exemplar `Ref` or `none yet`.

7. **Check conformance.** Start with a surface census — every modal, drawer, popover and
   palette with purpose, host and trigger (ui-detection § Editors and surfaces) — then walk
   entry by entry and type by type, sampling large files by pattern grep and naming regions
   left unread. Each violation: entry and rule id, type, expected (from `APP-DESIGN.md`),
   actual, `file:line`, recorded per app-patterns § Recording findings. Record one
   conformant exemplar per rule where one exists — it is what a fix copies. A rule with
   zero violations and zero exemplars has not been checked; one satisfied only because
   step 3 loosened it says "satisfied by decision" and names the obligation that remains.

8. **Write `findings.md` and `plan.md`** into the output directory. Findings grouped by
   rule, with a score table (violations, exemplars, per rule; a finding filed under another
   rule shows as `(+n)`) — counts here and in § Changelog are computed by grep over the
   artifacts, not typed. The plan orders systemic changes first — a shared editor, the
   action registry, one confirm component — because each closes violations across every
   type; then per-type changes, each listing the
   violations it closes and the files it touches. End with a coverage table: every
   violation maps to a change or is `accepted`. Mark the entries the plan changes `(change)`
   in `APP-DESIGN.md`. Run the citation check (ui-detection § Verifying citations) over
   every artifact, `APP-DESIGN.md` included.

9. **Present the decisions, then the score.** Global entries and floorplans first, then the
   score table. Changes the user rejects go into § Exceptions with their reason, answers go
   into the entries they settle, and § Changelog records the run — so the next conformance
   run does not report them again.

**Done when** every rule P1–P17 has a decision with a reason, every non-system type has a
floorplan row in `APP-DESIGN.md`, every rule has been checked with violations and exemplars
counted, every violation cites a `file:line` the citation check passes and is covered by a
change or accepted, and the step-5 questions are answered or open in § Open.
