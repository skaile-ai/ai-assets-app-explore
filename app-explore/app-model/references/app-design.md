# APP-DESIGN.md — where an app's interaction decisions live

`APP-DESIGN.md` at the app root records how this app applies the rulebook: where each
object lives, which surface edits what, how saving, messages, popups and buttons work, how
people find and trigger things. It sits beside `DESIGN.md` (how it looks) and `CONTEXT.md`
(what things are called) and repeats neither. It holds *decisions*; findings, plans and
questions stay in the run's output directory. Coding agents and reviewers cite its ids
(`MOD-2`) instead of re-deriving a rule.

In a monorepo each app has its own file at its own root. When `CLAUDE.md`/`AGENTS.md` do not
link it, the plan says so; the skills do not edit those files.

## Shape

```markdown
---
app: <name>
updated: YYYY-MM-DD
rulebook: app-patterns P1–P17
companions: { visual: DESIGN.md, glossary: CONTEXT.md, adr: docs/adr/ }
---
# App design – <name>
## Context              scale, roles, UI stack – the facts the decisions rest on
## Objects              floorplan table, representations, entity-page entries
## Surfaces             SURF
## Modals               MOD
## Popups               POP
## Editing              EDIT
## Messages             MSG
## Buttons              BTN
## Search and commands  FIND
## Navigation           NAV
## Language             LANG
## Exceptions           table: id · entry or rule · exception · reason
## Open                 table: id · question · recommendation
## Changelog            one line per write: date · skill or person · what changed
```

A section with nothing decided yet is left out; whoever fills it later inserts it in this
order. Entries are one line each, not hard-wrapped, so a diff shows one decision per line.
Budget about 100–200 lines; past that, the floorplan table moves to
`docs/app-design/objects.md` and § Objects links it.

§ Objects holds, in order: the floorplan table (one row per type users act on — a `system`
type users only read is left out; class from
app-patterns, plus `simple` or `complex` for core and supporting types), the representations
table (`row`, `card`, `chip`, `peek` with their field subsets), per type its `task → surface`
list and palette actions, then the OBJ entries. Table rows are decided entries like any
other: a row resting on an unanswered question ends with `[open Qn]`, and a single cell
resting on one carries it in the cell (`change [open Q1]`).

| area | decides | rules |
|---|---|---|
| OBJ | per type: class, home, index, editor, create, delete, representations, in search, editing tasks and their surfaces; entity-page anatomy; edit model of a page | P1, P2, P4–P8 |
| SURF | the edit-surface ladder and its local thresholds; what a drawer may host | P5 |
| MOD | footer layout, dismissal while dirty, stacking, linkable dialogs, narrow viewports | P5, P7, P14 |
| POP | tooltip, popover, dropdown menu, peek | P16, P2 |
| EDIT | save model, unsaved changes, validation and disabled Save, create flow, confirm vs undo | P14, P6, P7 |
| MSG | toast vs inline alert vs nothing, announcements, empty states | P15 |
| BTN | icon vs text, hierarchy, placement, labels, destructive styling, action registry | P17, P11 |
| FIND | search entry and scope, results page, palette content and order, shortcuts, list filters | P8–P11 |
| NAV | primary navigation, deep links | P12, P9 |
| LANG | nouns from the glossary, the verb set | P13, P11 |

## Entries

One bullet per decision — imperative, applicable in a pull request without opening a source:

```markdown
- **MOD-2 Dirty dialogs ask before closing, in place.** <the rule>. *Why:* <one line: app fact or source>. *Ref:* `path/from/repo/root.vue:12-30`. *Rules:* P5, P14 adapt. [open Q3]
- **MOD-3 No modal over a modal.** <the rule>; two dialogs still stack it (change). *Ref:* none yet. *Change:* `path/to/a.vue:234`, `path/to/b.vue:241`. *Rules:* P5, P7.
```

- **Ids** are `AREA-n`, never reused. A revised decision keeps its id; a dropped one is
  struck through in § Changelog, not renumbered.
- **Ref** is the exemplar a fix copies; `Ref: none yet` when the code has none. A
  deviation the code still has is marked `(change)` in the rule text and its sites go in a
  `*Change:*` field after *Ref* — `*Change:* path/a.vue:12, path/b.vue:40` — not explained;
  past three sites, the count and the first site — the rest are in the findings. A
  deviation that is an absence (a missing query parameter) has no site; the rule text
  names what is missing.
- **Rules** names the rules the entry applies; `adapt` after a rule id when the entry
  changes the rule's form (P5's ~8 fields become ~12). An adapted rule is not an exception.
- **Contracts** sit in the entry that owns them, as a short code block in the stack's
  syntax: the editor shape (`mode`, section subset, events) under the OBJ entry, the action
  registry entry (`id`, `label`, `icon`, `shortcut`, `scope`, `available`, `run`) under BTN.
- **§ Exceptions** holds rejected rules and accepted deviations from an entry, each with
  its reason.
- **Status:** an entry is decided unless it carries `[open Qn]`; the question and its
  recommended answer are in § Open. A § Open row stands alone — question, options,
  recommendation and its reason — without pointing to a run's `questions.md`, because the
  person who answers it may never see that file; an empty § Open says "No open questions."
  A rule adopted unchanged is decided by adoption and needs no question; `[open Qn]` marks
  an entry that rests on a question asked and not yet answered. Every citation in the file
  passes the ui-detection citation check, like any artifact.

## Reading it

Every skill reads the file at step 1, as intent, before judging anything:

- A decided entry replaces the default of the rules it cites. Code that deviates is one
  finding, filed under the entry with the rule tagged (`MOD-2 / P5`), counted once.
- A deviation listed in § Exceptions is not reported.
- An `[open Qn]` entry is judged by its recommendation, and the finding is tagged `[Qn]`.
- An entry that removes a rule's obligation without being listed as an exception is
  reported once, as a question for § Open — never silently followed or overruled.
- An entry whose *Why* or *Ref* the code contradicts (the cited line says otherwise, the
  stated fact is false) is reported once, as a question for § Open with the evidence; the
  entry stays as written until the user answers.

## Writing it

- **Who writes what.** `experience-app-guideline` is the writer of record: it creates the file
  and keeps every section. `experience-app-objects` writes § Objects — which surface edits what,
  per type — and § Language nouns; app-wide behaviour (save model, confirm vs undo) is EDIT
  and stays with the writer of record. `experience-app-interview` writes any section, but only
  what the user answered; it is where `[open Qn]` entries are settled, decided entries are
  revised and § Exceptions are confirmed. Anything a skill would decide outside its
  sections goes to § Open as a proposal.
- **`(change)` marks are findings, not decisions.** Any skill adds one to any entry, with
  the deviating sites in *Change:*, when its run shows the code breaks that entry.
- **Exceptions need the user.** A deviation enters § Exceptions only on the user's answer;
  proposed without one, it is a question in § Open (`keep as exception?`).
- **Missing file.** The first skill to run creates it from the shape above with the
  sections it fills, plus § Open and § Changelog.
- **Existing file.** Update in place: add entries, add `(change)` marks, never rewrite a
  decided entry. Flipping one needs the user's answer; until then it is a question in § Open.
- **No user available.** Entries that rest on a recommended answer the user has not given
  carry `[open Qn]` — the file never presents an unconfirmed choice as decided. New
  questions take the next number after the highest `Qn` the file has ever used, § Changelog
  included; the run's `questions.md` uses the same ids.
- **Every write** adds one § Changelog line and sets `updated:`.
