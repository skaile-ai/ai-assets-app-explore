# Finding the app's structure in code

Where screens, objects, editors and finders hide, per stack. Read the row for the detected
stack; when a pattern is missing, extend the table rather than guessing.

## Intent and vocabulary

Before judging, read the app's `APP-DESIGN.md` (`app-design.md` § Reading it), the repo's
`CONTEXT.md` or glossary, its ADRs (`docs/adr/`, `docs/decisions/`), any UI or design
concept (`docs/*konzept*`, `docs/*design*`, `docs/ui*` — headings first, then the parts a
rule touches) and `CLAUDE.md`/`AGENTS.md`: they name the objects (P13) and record
deviations that were decided on purpose. A decision such a document holds that
`APP-DESIGN.md` lacks becomes an entry citing it, not a finding.

## Screens (routes)

| stack | where |
|---|---|
| Nuxt | `app/pages/**` or `pages/**` (file = route, `[id]` = param); `layouts/`; `definePageMeta` |
| Next.js | `app/**/page.tsx` (App Router), `pages/**` (Pages Router); `layout.tsx`; parallel/intercepting routes `@slot`, `(.)x` are modal routes |
| SvelteKit | `src/routes/**/+page.svelte`, `+layout.svelte` |
| React SPA | router config: `createBrowserRouter`, `<Route path=`, TanStack `createFileRoute` |
| Vue SPA | `createRouter({ routes })` |

Tabs, steps and sub-views that change content without a route count as screens when they
show a different object or task; note them as `route#tab`. Overlays mounted in the layout
(create modals, palettes, inbox drawers) are screens too and are easy to miss.

## Objects (types)

In priority order: database schema (`schema.prisma`, Drizzle `pgTable`, migrations, Directus
`snapshot.yaml`/collections, Supabase types), shared TS types/Zod schemas
(`shared/`, `types/`, `*.schema.ts`), API routes (`server/api/**`, `app/api/**`), then the
nouns in page titles and nav labels. The schema's name is evidence, the UI's label is what
the user calls it — record both when they differ. A hand-maintained type file can drift
from the real schema; mark names taken only from call sites as inferred.

## Editors and surfaces

| surface | grep for |
|---|---|
| modal | `Modal`, `Dialog`, `UModal`, `<dialog`, `AlertDialog`, `v-dialog`, `showModal` |
| drawer | `Drawer`, `Sheet`, `Slideover`, `USlideover`, `SidePanel`, `Offcanvas` — in Nuxt UI `USlideover` is the side panel, `UDrawer` a bottom sheet |
| popover | `Popover`, `UPopover`, `Popper`, `Dropdown` containing inputs |
| inline | `contenteditable`, `@blur`/`onBlur` + save call on a single input, `isEditing` toggles, `InlineEdit`, `EditableText` |
| page editor | a route whose component holds a `<form>`/`UForm`/`useForm` bound to one object |

An *editor* is the component that owns the field set and the submit for one object type.
Find them by the save call (`$fetch(... method: 'PATCH'|'POST')`, `useMutation`,
`updateItem`, `createItem`, server actions) and walk up to the component that renders the
inputs. Two components posting to the same endpoint with different field sets are two
editors for one type.

Every overlay match needs reading for its *purpose* — editor, confirm, picker, info — and
its *host*: a surface census (one row per overlay: purpose, host, trigger) is where bespoke
confirm dialogs and stacked modals show up. Stacking is state, not markup: an editor whose
open-flag stays set while a confirm opens is a modal on a modal.

## Finders

| thing | grep for |
|---|---|
| command palette | `cmdk`, `kbar`, `UCommandPalette`, `UDashboardSearch`, `UDashboardSearchButton`, `CommandDialog`, `ninja-keys`, `meta+k`, `ctrl+k`, `defineShortcuts` |
| global search | a search input in the layout/header component, `/search` route, search API endpoint |
| shortcuts | `useMagicKeys`, `hotkeys`, `useHotkeys`, `defineShortcuts`, `keydown` listeners on `window`/`document` |
| action definitions | arrays of `{ label, icon, click/onSelect }` reused by menus — the seed of an action registry |

## Saving, messages, popups and buttons

| rule | grep for |
|---|---|
| save model (P14) | autosave: `watchDebounced`, `useDebounceFn`, `@change`/`@update:model-value` with a save call; explicit: `type="submit"`, `@submit`; leave guards: `beforeunload`, `onBeforeRouteLeave`, `useBlocker`, `dismissible`, `prevent-close`, `@close:prevent` |
| messages (P15) | toasts: `useToast`, `toast.add`, `toast(`, `sonner`, `notify`; inline: `UAlert`, `Alert`, `role="alert"`, the app's own error strip; empty states: `UEmpty`, `EmptyState`, `v-if="!items.length"` |
| popups (P16) | `UTooltip`, `Tooltip`, `v-tooltip`, native `title=` on interactive elements; `UPopover`; `UDropdownMenu`, `DropdownMenu`, `Menu` |
| buttons (P17) | icon-only: a button with `icon=` and neither `label=` nor slot text; `aria-label`; hierarchy: `variant=`/`color=` per view, count of solid primaries; destructive: `color="error"`/`danger`/`destructive` |

Toasts are classified by colour or type: error- and warning-coloured toasts are where P15
findings come from, unless `APP-DESIGN.md` decides that channel. Buttons are counted by
parsing tags, not by line grep — a multi-line `<UButton …>` splits its attributes across
lines. A "view" is a page or an overlay (modal, drawer) together with the components it
renders in place; a mounted component's own overlay is a view of its own. The scanner
reports per file, so add up a page's solid primaries with those of the components it
renders in place before judging P17. For Vue, JSX and Svelte markup, adapting the tag
names and the stack's default variant:

```python
import re, sys, pathlib  # python3 scan.py app/  -> one line per button
TAG = re.compile(r'<(UButton|Button|button)\b((?:[^>"\']|"[^"]*"|\'[^\']*\')*?)(/>|>(.*?)</\1>)', re.S)
for f in pathlib.Path(sys.argv[1]).rglob('*'):
    if f.suffix not in ('.vue', '.tsx', '.jsx', '.svelte') or 'node_modules' in f.parts: continue
    s = f.read_text(errors='ignore')
    for m in TAG.finditer(s):
        a, text = m.group(2), re.sub(r'<[^>]+>', '', m.group(4) or '').strip()
        icon_only = bool(re.search(r'\bicon=', a) and not re.search(r'(?<![\w-]):?label=', a) and not text)
        solid = not re.search(r'\b(variant|color)=', a)  # stack default: Nuxt UI's UButton is solid primary
        tooltip = 'Tooltip' in s[max(0, m.start() - 300):m.start()]
        print(f"{f}:{s.count(chr(10), 0, m.start()) + 1}", f"icon_only={icon_only}",
              f"named={'aria-label=' in a}", f"tooltip={tooltip}", f"solid={solid}", sep='\t')
```

## Generated and vendored code

Skip `node_modules/`, `.nuxt/`, `.output/`, `.next/`, `dist/`, `build/`, lockfiles and
vendored third-party code. A vendored UI library is evidence of available components, not
of app screens; the app's own module under `vendor/` is app code.
Files too large to read whole are sampled by grep per rule; say which regions went unread.

## Verifying citations

A cited `file:line` that does not exist turns a finding into an opinion. Cite the full path
from the repository root every time, also on the second mention — `druck/[id].vue:12` or
`components/X.vue:5` under an unstated root can be neither opened nor checked. Check every
citation mechanically before finishing — existence and range, run from the repository root:

```sh
grep -ohE '[^[:space:]:`"(,;]+\.(vue|[cm]?[jt]sx?|svelte|py|md|ya?ml|json):[0-9]+(-[0-9]+)?' <artifacts> | sort -u |
while IFS=: read -r f l; do [ -f "$f" ] || { echo "missing $f"; continue; }
  [ "${l%-*}" -le "$(wc -l < "$f")" ] || echo "out of range $f:$l"; done
```

A bare file name (`Abschnitt.vue:12`) reports as missing — that is the point: cite it from
the root. Shorthand that leans on an earlier mention escapes the script, so this must print
nothing: ``grep -nE '`:[0-9]+' <artifacts>``. Prose locations ("lines 40–60 of `X.vue`")
are not citations; write them as `path:40-60`.

Then read a sample of the cited lines for meaning — the script proves the line exists, not
that it says what the finding claims.
