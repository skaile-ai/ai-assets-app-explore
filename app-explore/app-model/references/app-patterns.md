# App patterns — where information lives and how it is edited

The rulebook the app-architecture skills apply. Each rule has an id (`P1`…`P17`) so a
finding, an `APP-DESIGN.md` entry or a plan step can cite it in one token. An **object** is a noun
the user manages (OOUX) — including a *derived* object the UI shows but no table stores
(an inbox item computed from deadlines); an **attribute** is one of its fields; a
**surface** is the UI container an editor is hosted in. Every object has one **class**:
`core` — users reach it from navigation or search and maintain it in its own right (it has
an index, P8); `supporting` — reached only through other objects, but with a life of its
own (shared, linked from several parents); `child` — exists only inside one parent and
dies with it; `junction` — a relationship carrying attributes of its own; `system` —
created by the app or an import, its fields read-only to users (mails received, logs,
derived objects). An object with its own nav entry and index is `core`, whatever its
field count. The rules are defaults: an app's
own decisions on them live in its `APP-DESIGN.md` (`app-design.md`), and a decided entry
there takes precedence over the rule it cites.

## Where information lives

**P1 — Canonical home.** Every attribute has exactly one home: the detail view of the
object that owns it. That is where it is shown in full and where it is edited. An attribute
that belongs to a relationship (a role on a membership, a price on an order line) lives on
the junction object, not on either side.

**P2 — Representations.** Everywhere else an object appears as a declared
*representation* — `row` (list/table), `card`, `chip` (inline reference), `peek` (hover or
side preview) — each a fixed subset of attributes, the same subset on every screen, and each
links to the canonical home. A representation is defined once per object type and reused;
two screens rendering the same object with different subsets is a second, undeclared
representation.

**P3 — Redundancy test.** Repetition is legitimate when it is a representation (P2), a
breadcrumb or page title naming the current object, or an aggregate of children (count,
sum, status rollup) that links to them. It is redundant when:
- the same attribute appears twice within one viewport (header and body, card and sidebar);
- the same attribute is *editable* in more than one place (violates P1);
- a derived value (status, deadline, totals) is computed in more than one place, so two
  screens can disagree — or computed once and *stored*, so it goes stale when its inputs
  change (a generated invitation text that keeps the old date);
- a screen exists only to show a subset another screen already shows, with no task of its own.

## How objects are edited

**P4 — One editor per object type.** Each object type has one editor component: one field
set, one validation schema, one set of labels and help texts. Page, drawer and modal are
*hosts* for that editor; the host supplies chrome (title, close, primary action placement),
never fields. Partial editors (one section of a complex object) are slices of the same
component, not re-implementations.

**P5 — Edit-surface ladder.** Choose the least interruptive surface the task fits; move up
only when a criterion forces it.

| surface | use when | move up when |
|---|---|---|
| inline (click-to-edit, autosave) | one scalar attribute, valid on its own, edited often (status, title, assignee, date) | the change needs other fields, review, or is costly to undo |
| popover | 2–3 tightly coupled fields (date range, time + timezone, picker with search) | more fields, or the user needs to see the result in context |
| modal | one self-contained object or section, ≤ ~8 fields, one step, no need to read the page behind it; destructive confirmations | the user must reference or copy from the background, or the form grows sections |
| drawer / side panel | medium form while the list or page behind stays readable — triage row by row, edit-next | the object has child collections or several sections |
| modal or drawer with URL (`?item=<id>`) | as either row above, but the open item must be linkable, shareable or survive reload | the object has child collections or several sections |
| page (object page) | core object with sections, child collections, multi-step or long work, drafts, deep links, collaboration | — |

Hard limits: no modal on top of a modal — a confirmation raised from an open editor replaces
the editor's footer or content in place rather than stacking (P7 decides *whether* to
confirm, this decides *where*); no tabs or wizard inside a modal; an error or a feature
announcement is never a modal. A surface choice is per *editing task*, so one object can
be edited inline for its status, in a modal for its contact data and on its page for
everything else — all through the one editor of P4.

**P6 — Create.** Creation uses the same editor in *create mode*. Simple objects: modal or
drawer, then stay in context. Complex objects: a quick-create modal asking only the
required fields, then navigate to the new object's page. "Add" (attach an existing object)
is a picker, never the create editor.

**P7 — Delete and destructive actions.** Confirmation scales with cost: undo (P15 says
where it appears) for cheap, reversible deletes; confirm dialog naming the object and its
consequences (children, links) for irreversible ones, its buttons saying what happens
("Delete room" / "Keep"), none of them the default. One confirm component, app-wide.

**P8 — One index per core object.** Each core object has one list screen with filter,
sort, search and saved views. A second list of the same objects is a saved view or a
filter of the first, not another screen with its own columns and row actions.

## Finding and doing

**P9 — Global search finds nouns.** One search entry point, reachable from every screen,
searching every core object type; results grouped by type, each result a `row`
representation that opens the canonical home. A full results page carries the filters.

**P10 — Command palette (Cmd/Ctrl-K) finds and does.** It lists navigation targets,
objects and *actions*. Context first: on an object's page its actions rank above global
ones. Every palette action also exists in the visible UI — the palette accelerates, it is
never the only path — and shows its shortcut where one exists. Search and palette are one
component in small apps (search is a mode of the palette) and side by side when search is
a core feature.

**P11 — One action registry.** Every action (create, edit, archive, assign, export…) is
defined once with label, icon, permission, availability rule and shortcut, and that
definition feeds buttons, row menus, bulk actions, the palette and shortcuts. Labels
follow one verb set: *Create* (new), *Add* (attach existing), *Edit*/*Save*, *Delete*,
*Remove* (detach).

**P12 — Navigation from objects.** Primary navigation lists core objects (their P8
indexes) and the few cross-object workspaces (inbox, dashboard, calendar) that have a task
of their own; supporting objects are reached through their parent. A top-level entry per
feature or per settings page is a menu of the file system, not of the product.

## Naming

**P13 — One noun per object.** Each object and attribute has one user-facing name, taken
from the project glossary (`CONTEXT.md`, `glossary.md`) where one exists, and used
unchanged in navigation, page titles, editor labels, representations, palette entries and
messages. A field labelled three ways across three editors is one P13 finding, not three.

## Saving, messages, popups and buttons

**P14 — One save model per form.** Explicit *Save* for forms and declarative controls (text
fields, checkbox groups, radios, multi-selects); autosave for imperative controls
(switches, segmented controls) and P5's inline rung, with an inline "saving / saved" state
and an inline error with retry that stays until the value is saved. One form never mixes
both. Leaving with unsaved changes asks — in-app for in-app navigation, `beforeunload` for
the browser — and only when something would be lost; a dialog that can hold unsaved
changes does not close on a backdrop click.

**P15 — Messages by channel.** A result visible on the page needs no message; a success
that is not visible is a toast; an error or blocking condition is an inline alert where it
applies, with a way to recover, staying until resolved — never a toast, never a modal; an
announcement is a contextual hint where the feature lives, never a modal; an empty state
says what belongs there and offers the first action. A toast carries no action other than
P7's undo, and that undo stays reachable by keyboard — otherwise it goes inline.

**P16 — Popups by purpose.** A tooltip is short plain text, opens on hover *and* keyboard
focus, holds nothing needed to finish the task and nothing clickable — the native `title`
attribute fails the focus part. A popover opens on click and may hold links, actions, the
fields of P5's popover rung or a `peek` (P2). A dropdown menu holds actions or one choice;
once it needs search, filters or multi-select it is a dialog with Save and Cancel.

**P17 — Buttons say what they do.** A button carries a text label; the icon is optional and
leads. Icon-only is for repeated, universally known actions in toolbars and rows (close,
previous/next, reload, overflow), always with an accessible name and a tooltip (P16), never
for a view's primary or create action. One primary button per view or dialog, the rest of
lower emphasis; destructive buttons use the error colour and sit apart from benign ones.
Labels are active verbs from P11's verb set, with the object where unclear — never "OK" or
"Yes".

## Recording findings

- **One finding per distinct cause**, filed under the most specific rule and
  cross-referenced to the others it also breaks — never counted twice.
- **Severity:** `high` — users can see two values disagree, lose an edit, or act on stale
  data; `medium` — an inconsistency users have to learn; `low` — clutter or hygiene.
- **Kind:** P1–P8 and P13–P17 findings are *consistency* defects in existing code; P9–P12
  findings are often *completeness* gaps (the palette lacks actions). Mark completeness gaps
  so a count never weighs a missing feature like a broken one.
- **Status:** `open`, or `accepted` with the reason when the team keeps a deviation on
  purpose. An accepted deviation goes into `APP-DESIGN.md` § Exceptions, so the next run
  does not report it again.
- **Intent first:** a deviation the repo's ADRs or `CONTEXT.md` already decided is either
  an accepted exception or an *unimplemented decision* — say which, never "design flaw".
- **Absences** (no deep link, a type missing from search) have no line of their own: cite
  `absence: <what is missing>` with the nearest `file:line` where it would sit.

## Sources

- OOUX / ORCA — Sophia Prater, [A List Apart](https://alistapart.com/article/ooux-a-foundation-for-interaction-design/), [ooux.com](https://ooux.com/resources/introducing-orca-the-third-diamond-in-your-ux-process)
- SAP Fiori — [Object Handling](https://www.sap.com/design-system/fiori-design-web/v1-148/foundations/best-practices/global-patterns/object-handling/manage-objects) (dialog for ≤ 8 fields, object page otherwise; partial/local/global edit flows; Create vs Add)
- Vitaly Friedman — [Modal vs. Separate Page: UX Decision Tree](https://www.smashingmagazine.com/2026/03/modal-separate-page-ux-decision-tree/); Ryan Neufeld — [Modal vs Page framework](https://uxplanet.org/modal-vs-page-a-decision-making-framework-34453e911129)
- [PatternFly inline edit](https://v5-archive.patternfly.org/components/inline-edit/design-guidelines); NN/g — [Modal & Nonmodal Dialogs](https://www.nngroup.com/articles/modal-nonmodal-dialog)
- Sam Solomon — [Designing Command Palettes](https://solomon.io/designing-command-palettes/) (find vs do, context awareness, search placement)
- NN/g — [Icon Usability](https://www.nngroup.com/articles/icon-usability/), [Tooltip Guidelines](https://www.nngroup.com/articles/tooltip-guidelines/), [Confirmation Dialogs](https://www.nngroup.com/articles/confirmation-dialog/) (P7, P16, P17)
- Primer — [Saving](https://primer.style/product/ui-patterns/saving/) (save model by control type), [Dialog](https://primer.style/product/components/dialog/guidelines) (backdrop and dirty forms); Cloudscape — [Unsaved changes](https://cloudscape.design/patterns/general/unsaved-changes/) (P14)
- GitLab Pajamas — [Choosing a messaging pattern](https://design.gitlab.com/patterns/choosing-a-messaging-pattern), [Saving and feedback](https://design.gitlab.com/patterns/saving-and-feedback) (P14, P15, P16)
