# ai-assets-app-explore

skaile library with one skill that explores a running web app the way a user would, without its source code, and reports what a user perceives: the objects the app shows, the tasks it supports, how screens and functions are reached, and how clear each screen looks. Published under `@skaile-ai`.

| Asset | Kind | Description |
|---|---|---|
| `app-explore` | skill | Crawls the app in a hidden browser into a graph of states (pages, dialogs, menus, tab panels), screenshots each one with numbered marks on every interactive element, and renders a static HTML report with an annotated screenshot gallery. |

## Use

```bash
skaile source add skaile-ai/ai-assets-app-explore
skaile add skill:@skaile-ai/app-explore
```

Then, in an agent session:

```text
app-explore <url> [sandbox] [since <path>|since auto] [budget <n>]
```

- Read-only by default: a guard in the page rejects writes (PUT, PATCH, DELETE, POST except GraphQL queries and allow-listed endpoints) and the crawler never presses delete, save, send or logout. `sandbox` allows writes for apps whose data may change; logout stays blocked.
- `since auto` builds on the newest previous report for the same host; `since <path>` names one.
- `budget <n>` caps the number of states (default 60).

Requires `@skaile-ai/report` ≥ 0.6.0 (installed as a dependency) and omp's eval `browser`. Login walls are passed by borrowing the session from your Chrome through the omp browser relay, or by signing in once in a headed window.

## Files

| File | Job |
|---|---|
| `app-explore/app-explore/SKILL.md` | The steps the agent follows. |
| `app-explore/app-explore/crawl.mjs` | Browser helpers imported in an omp JavaScript eval cell: login handling, write guard, Set-of-Mark marks, DOM geometry checks, dHash, breadth-first crawl. |

`skaile.manifest.yaml` is the publish inventory; `skaile library index ai-assets-app-explore` keeps it in step with the files on disk.

## License

MIT, see [LICENSE](LICENSE).
