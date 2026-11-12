---
name: experience-app-interview
description: Use when an app's interaction decisions should come from the people
  who own it — interviews the user area by area (objects, surfaces, modals,
  popups, editing, messages, buttons, search, command palette, navigation,
  language), each question with a recommendation grounded in the code, and
  writes the answers into APP-DESIGN.md as decided entries. Also settles the
  open questions an experience-app-guideline, experience-app-objects or app-model run left,
  and works for an app not built yet. Triggers on 'interview me for
  APP-DESIGN.md', 'decide our UI rules together', 'go through the open
  questions', 'write APP-DESIGN.md with me'.
metadata:
  version: 0.4.0
  publisher: skaile-ai
  requires: "app-model"
  stage: alpha
---

# experience-app-interview

Writes `APP-DESIGN.md` at the app root from the user's answers. The analysis skills
(`experience-app-guideline`, `experience-app-objects`) propose decisions and leave the contested
ones as `[open Qn]`; this skill is where a person decides them. It asks, it does not audit:
the code is read only to ground each recommendation and to name the exemplar a fix copies.
No application code changes.

Read `<app-model dir>/references/app-design.md` (shape, entries, writing rules) and
`references/decision-catalogue.md` (the agenda) before step 1; `<app-model dir>/references/app-patterns.md`
gives each rule's default and `<app-model dir>/references/ui-detection.md` where the code shows today's
behaviour and how citations are checked.

`<app-model dir>` is the `app-model` skill's directory, which holds the references this skill shares with
`experience-app-objects` and `experience-app-guideline`: the first of `~/.agents/skills/app-model`,
`~/.claude/skills/app-model` and `~/.omp/agent/skills/app-model` that holds `references/app-patterns.md`.

**The user is required.** Without one, stop after step 3: write the prepared rounds to
`interview.md` in `_concept/02_grounding/findings/experience-app-interview/` (created if
missing) so they can be answered later, and leave `APP-DESIGN.md` unchanged.

**Subagents.** While the user answers one round, the code look-ups for the next can run in a
subagent on a small, fast model (Claude Haiku or Sonnet; pick it when spawning). Brief it
with the ui-detection patterns for that area and the citation rule: paths from the
repository root, a bare file name is a failed citation. Recommendations stay with you.

## Steps

1. **Fix the target.** Confirm the app root; a monorepo with several apps is a question,
   not a guess. Read `APP-DESIGN.md` if it exists, the README, the glossary, the ADRs and
   UI concepts under `docs/` (ui-detection § Intent). Decided entries and § Exceptions are
   settled; they are asked again only when the user wants to revise one. When there is no
   code yet, recommendations come from the catalogue defaults alone and entries get
   `Ref: none yet`.

2. **Build the agenda** in this order, leaving out what the file already decides:
   - § Open of an existing file, lowest `Qn` first — answering what earlier runs could not
     decide is usually the most valuable part of the session;
   - § Context: scale, roles and UI stack, drafted from the code and confirmed in one
     question;
   - § Objects: the types the app manages (schema, shared types, nav), their class from
     app-patterns and their floorplan row;
   - the `decide` rows of an `app-model` compare register, when
     `_concept/02_grounding/findings/app-model/compare.yaml` exists: one row per mismatch
     with `suggestion: decide`, high and medium sev first, asked with its values per source
     (code, docs, app) and their evidence as the "what the app does today". The
     recommendation is the value of the source that wins under app-model's merge
     precedence (its SKILL.md § Compare); the answer goes into the entry of its area
     (§ Objects for names, classes and homes, § Language for `MM-name`), and its mismatch
     id goes into the entry's *Ref*;
   - the catalogue areas in the order of app-design § Shape, one row per missing entry.
   Match catalogue rows to existing entries by topic, not by id — ids differ between the
   catalogue and a written file; a new entry takes the next free number in its area. Show
   the agenda with a count per block and that row → entry mapping, and let the user
   choose: everything, only the open questions, or named areas. The user may stop after
   any round.

3. **Prepare each question before asking it.** Per agenda row: what the app does today
   (the ui-detection grep for it; one `file:line` that shows it, a count and the first site
   when it happens in many places, or "nothing found"), the rule's default from the
   catalogue, and for ⚖ rows the competing source. Recommend what
   the code already does when it passes the rule — confirming beats redesigning — and the
   default otherwise. State today's behaviour in one line in the user's terms — what a
   user of the app sees, not component or field names — so the user can decide without
   opening the code. An option that deletes stored data carries the count of affected
   records, or "count not checked". Before showing a round, run the citation check over
   its text and re-read the cited lines: a wrong fact in a question misleads the decision.

4. **Ask in rounds.** One block or area per round, at most five questions:
   - ⚖ rows, rows where the code differs from the default, and every § Open question are
     questions of their own: two to four options, the recommended one first, one line of
     consequence each;
   - rows where the code already matches the default are batched into one question,
     "adopt these defaults?", listing them; the user can pull any row out;
   - § Objects goes as a draft floorplan table derived from the code; ask only the
     contested cells (class calls, homes, create flow), not every cell;
   - "skip" or "later" keeps or creates an `[open Qn]` with the recommendation; a question
     asked and answered in the same round needs no `Qn`.
   When an answer needs interpretation to become a rule, read the rule back at the start
   of the next round. Ask in the user's language; entry ids, and the file's own language,
   stay as they are.

5. **Write after every round**, in place, per app-design § Writing it, so stopping loses
   nothing:
   - each answer becomes an entry in its area, imperative enough to apply in a pull
     request: *Why* is the user's reason (or "decided in interview, <date>"), *Ref* the
     exemplar from step 3 or `none yet`, *Rules* the rule ids, `adapt` where the answer
     changes a rule's form;
   - code that breaks a new entry, seen while preparing, gets `(change)` with its sites in
     *Change:* — this is not a conformance pass, so say in § Changelog that it was not one;
   - an answered `[open Qn]` loses its mark, the answer goes into the entry, the row
     leaves § Open; a deviation the user keeps on purpose goes to § Exceptions with the
     user's reason; a revised decided entry keeps its id;
   - one § Changelog line per round: date, "interview with <name>", the ids decided,
     revised and left open; set `updated:`.

6. **Close the session.** Run the citation check (ui-detection § Verifying citations) over
   `APP-DESIGN.md` and the shorthand grep; both print nothing. Report: entries decided,
   revised and still open, `(change)` marks added, and the agenda rows not reached. When
   entries were added or flipped, recommend an `experience-app-guideline` run to check the code
   against them.

**Done when** every agenda row the user chose is decided, revised, or open with a
recommendation in § Open; every entry written this session carries *Rules* and a *Ref* or
`none yet`; § Changelog has a line per round; and the citation check passes.
