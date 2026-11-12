# Decision catalogue — what an interview asks, area by area

The agenda for `experience-app-interview`. Each row is one decision `APP-DESIGN.md` should
hold, with the default the cited source gives. ⚖ marks rows where sources disagree: these
are the questions worth the user's time, because without a recorded choice two developers
pick two answers. Rows without ⚖ are offered as "take the default?" and batched. The
`id` is the suggested entry id in its area; an existing file's ids win.

### Objects and entity pages (OBJ)

| id | decision | research default | alternatives / conflict | source |
|---|---|---|---|---|
| OBJ-1 | floorplan per object type: home, index, editor, create, delete, representations, in search | core types get an object page, simple types a dialog | — | P1/P2/P4/P8; Fiori object handling |
| OBJ-2 | entity page anatomy | header with title, status, 3–5 key facts, primary action + overflow menu; sections with anchor navigation; child collections as tables inside their section | tabs instead of anchors when sections are heavy and independent | Fiori object page |
| OBJ-3 | edit model on the entity page | one edit mode at a time, one save per page or form | section-wise edit; whole-page draft (Fiori draft handling) | Primer Saving (placement); Fiori draft handling |

### Surfaces and modals (SURF, MOD)

| id | decision | research default | alternatives / conflict | source |
|---|---|---|---|---|
| SURF-1 | edit-surface ladder with local thresholds | inline → popover → modal (≤ ~8 fields) → drawer → page | the field limit is app-specific | P5; Fiori; Smashing decision tree |
| SURF-2 ⚖ | may a drawer host create/edit forms? | yes for triage and edit-next while the list stays readable (P5) | **Primer: side sheets not for create/edit forms, use a page** | P5; Primer Dialog |
| MOD-1 | modal anatomy | title required; × always visible; body scrolls; footer: primary rightmost, Cancel left of it, auxiliary (Delete) on the left | — | Primer Dialog, Primer Saving |
| MOD-2 | dismissal while dirty | backdrop does not dismiss a dialog that can hold unsaved changes; Esc/×/Cancel ask before discarding; ask only when something would be lost; no "don't ask again" | — | Primer Dialog (backdrop); Cloudscape unsaved changes |
| MOD-3 ⚖ | stacking | no modal over a modal; a confirmation replaces the footer | **Primer allows two nested dialogs with correct focus return** | P5; Primer Dialog |
| MOD-4 ⚖ | deep-linkable modals | modal/drawer with `?item=<id>` when the item must be linkable | **Primer: if it needs a link, prefer a page – a dimmed page loses context** | P5; Primer Dialog |
| MOD-5 | content limits | single column; no tabs, wizard or side navigation inside; never for errors or announcements | — | Primer Dialog; Smashing |
| MOD-6 | narrow viewports | centred dialog becomes full-screen or a bottom sheet | which of the two | Primer Dialog |

### Popups (POP)

| id | decision | research default | alternatives / conflict | source |
|---|---|---|---|---|
| POP-1 | tooltip | short plain text; opens on hover *and* keyboard focus; never holds information needed to finish the task; never interactive; used consistently or not at all | — | NN/g Tooltip guidelines; GitLab messaging |
| POP-2 | popover | opens on click (not hover, focus or load); may hold links, actions, 2–3 coupled fields or an object preview; Esc/outside click closes | — | GitLab messaging; P5 |
| POP-3 | dropdown menu | a list of actions or single choices only; once it gains search, filters or multi-select it is a dialog with Save/Cancel | — | Primer Saving (dropdown accessibility) |
| POP-4 | peek / hover card | preview of an object (`peek` representation) linking to the home; tap/click opens it on touch | hover-only preview | P2; NN/g (tooltips unavailable on touch) |

### Editing and saving (EDIT)

| id | decision | research default | alternatives / conflict | source |
|---|---|---|---|---|
| EDIT-1 | save model per control type | explicit save for forms and declarative controls (text, checkbox group, radio, native select, multi-select); autosave for imperative controls (switch, segmented control, single-select menu); never both in one form | autosave whole long forms (GitLab: per input, never whole forms) | Primer Saving; GitLab Saving |
| EDIT-2 | autosave feedback | inline "Saving…" / "Saved" near the control; a failure is an inline alert with retry that stays until saved, not a toast | — | GitLab Saving |
| EDIT-3 | unsaved changes on leave | in-app confirm for in-app navigation, `beforeunload` for browser actions, only when dirty | — | Cloudscape; Primer Saving; GitLab safety measure |
| EDIT-4 ⚖ | invalid or unchanged form: disable Save? | **Primer: never disable Save** – disabled buttons cannot be focused and are hard to read; validate on submit | disable until required fields are filled (common, Nuxt UI default) | Primer Saving (state) |
| EDIT-5 | create flow | simple: modal, stay in context; complex: quick-create with required fields, then go to the new object's page | — | P6; Primer Saving (redirecting) |
| EDIT-6 ⚖ | delete: confirm or undo | confirm only consequential, irreversible actions; name the object and its consequences; buttons say what happens ("Delete room" / "Keep"), no default on the destructive button; typed confirmation only for the rarest | **undo toast (P7, NN/g favour undo) vs GitLab: toasts cannot hold actions accessibly, undo goes inline** | NN/g Confirmation dialogs; GitLab messaging; P7 |
| EDIT-7 | validation timing | at field on blur and on submit; debounce live checks ~500 ms | — | GitLab delayed feedback |

### Messages (MSG)

The GitLab decision tree is the most complete source and orders the questions: does this message need to exist at all → result of the user's action → system condition → feature discovery → explanation → empty → catch-up later.

| id | decision | research default | source |
|---|---|---|---|
| MSG-1 | result visible on the page | show nothing, or a brief state on the control (check on the copy button) | GitLab messaging |
| MSG-2 | success not visible | toast, without actions | GitLab messaging |
| MSG-3 | errors and blocking conditions | inline alert with a recovery path, stays until resolved; never a toast, never a modal | GitLab messaging; P5 |
| MSG-4 | announcements | no notice, or a contextual hint where the feature lives; banner last; never a modal | GitLab messaging |
| MSG-5 | empty states | say what belongs here and offer the first action | GitLab messaging |

### Buttons (BTN)

| id | decision | research default | alternatives / conflict | source |
|---|---|---|---|---|
| BTN-1 | icon or text | text label, icon optional and leading; only home, print and search icons are near-universal | — | NN/g Icon usability |
| BTN-2 | when icon-only is allowed | repeated, universally known actions in dense toolbars and rows (close, search, previous/next, overflow ⋯); always `aria-label` plus a tooltip on hover and focus; never for the view's primary or create action | — | NN/g Icon usability; NN/g Tooltip guidelines |
| BTN-3 | hierarchy | one primary per view or dialog; secondary/ghost for the rest; toolbars and rows use low emphasis | — | Carbon button usage; Primer Saving (appearance) |
| BTN-4 ⚖ | placement | dialogs: bottom right, Cancel left of primary | **page forms: Primer bottom-left with Cancel right of Save**; many systems mirror dialogs | Primer Saving, Primer Dialog |
| BTN-5 | labels | active verb, plus the object where unclear ("Save profile"); no "OK", "Yes", "Done"; verb set from LANG | — | Primer Saving (text); NN/g Confirmation dialogs; P11 |
| BTN-6 | destructive actions | error colour; kept apart from benign actions | — | NN/g Proximity of consequential options (title only, unverified) |
| BTN-7 | action registry | every action defined once (label, icon, shortcut, availability) and rendered as button, menu item, palette entry and shortcut | — | P11 |

### Search and commands (FIND)

| id | decision | research default | alternatives / conflict | source |
|---|---|---|---|---|
| FIND-1 | central search entry | one entry point on every screen, in a fixed place (header or sidebar), with a shortcut | — | P9; Solomon |
| FIND-2 | search scope and results | every core object type, results grouped by type, each result opens the canonical home; recents when the query is empty | — | P9; Solomon; Setproduct (8 states) |
| FIND-3 | full results page | yes when search is a core feature (filters live there) | none in small apps | P9 |
| FIND-4 | search vs command palette | one component in small apps (search is a mode of the palette); separate when search is core | — | P10; Solomon |
| FIND-5 | palette content and order | context actions of the current object first, then navigation, objects, global actions; every entry also exists in the visible UI; shows its shortcut | — | P10; Solomon |
| FIND-6 | shortcuts | defined in the action registry; shown in palette and tooltips; single-key shortcuts never fire inside inputs `[INFERENCE]` | — | P11; Solomon |
| FIND-7 | list search and filters | one filter bar component per index; saved views only when the scale warrants them | — | P8 |

### Navigation and language (NAV, LANG)

| id | decision | research default | source |
|---|---|---|---|
| NAV-1 | primary navigation | core object indexes plus workspaces with a task of their own; supporting objects through their parent; settings under one entry | P12 |
| NAV-2 | deep links | every object home has a URL; search results and chips link there | P9; P2 |
| LANG-1 | vocabulary | one noun per object from the glossary; one verb set (create / add / edit / save / delete / remove, in the UI language) | P13; P11 |

Not catalogued: loading states, responsive layout and motion — visual or component
concerns for `DESIGN.md`.

## Sources

- NN/g – [Icon Usability](https://www.nngroup.com/articles/icon-usability/) (labels always visible; few universal icons); [Tooltip Guidelines](https://www.nngroup.com/articles/tooltip-guidelines/) (not for essential info; mouse and keyboard; consistent); [Confirmation Dialogs](https://www.nngroup.com/articles/confirmation-dialog/) (specific, action-named buttons, no default, typed confirm for rare cases, prefer undo); [Proximity of Consequential Options](https://www.nngroup.com/articles/proximity-consequential-options/) (title only, not read)
- Primer (GitHub) – [Saving](https://primer.style/product/ui-patterns/saving/) (explicit vs automatic by control type, never disable save, button placement, redirect after create); [Dialog guidelines](https://primer.style/product/components/dialog/guidelines) (anatomy, backdrop and dirty forms, nesting, deep linking, side sheets, bottom sheets)
- GitLab Pajamas – [Choosing a messaging pattern](https://design.gitlab.com/patterns/choosing-a-messaging-pattern) (decision tree for toast, alert, popover, tooltip, empty state); [Saving and feedback](https://design.gitlab.com/patterns/saving-and-feedback) (autosave per input, inline status, no actions in toasts, debounce)
- Cloudscape (AWS) – [Communicating unsaved changes](https://cloudscape.design/patterns/general/unsaved-changes/)
- Carbon – [Button usage](https://v10.carbondesignsystem.com/components/button/usage/) (hierarchy, low emphasis in toolbars; quoted via a search summary, page not opened)
- SAP Fiori – [Object Handling](https://www.sap.com/design-system/fiori-design-web/v1-148/foundations/best-practices/global-patterns/object-handling/manage-objects); [Object Page](https://www.sap.com/design-system/fiori-design-web/v1-145/page-types/floorplans/object-page) and [Draft Handling](https://www.sap.com/design-system/fiori-design-web/v1-145/foundations/best-practices/global-patterns/object-handling/draft-handling) (not opened; the OBJ-2/OBJ-3 defaults attributed to them are unverified)
- Sam Solomon – [Designing Command Palettes](https://solomon.io/designing-command-palettes/); Setproduct – [Command palette, 8 states](https://www.setproduct.com/blog/command-palette-ui-design-guide) (unverified, title only)
- Vitaly Friedman – [Modal vs. Separate Page decision tree](https://www.smashingmagazine.com/2026/03/modal-separate-page-ux-decision-tree/)
