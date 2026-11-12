# ai-assets-app-explore

skaile library of skills that describe an app's objects, tasks and screens and check them: `app-explore` explores a running web app the way a user would, without its source code, and reports what a user perceives; `app-model` builds one ontology of the app from its code, its docs and the running app, compares the three and maps its features; the `experience-app-*` skills turn the object model into interaction decisions in `APP-DESIGN.md`. Published under `@skaile-ai`.

| Asset | Kind | Description |
|---|---|---|
| `app-explore` | skill | Crawls the app in a hidden browser into a graph of states (pages, dialogs, menus, tab panels), screenshots each one with numbered marks on every interactive element, and renders a static HTML report with an annotated screenshot gallery. |
| `app-explore-walker`, `app-explore-critic` | agents | The persona walks and the visual critique of an `app-explore` run. |
| `app-model` | skill | Writes `app-model.<code,docs,app>.yaml` in one format (skaileup's vocabulary), aligns and merges them, lists every mismatch in `compare.md`, and with `map`/`propose` derives a feature map and proposes it into a skaileup `_concept/` tree. Holds the references the `experience-app-*` skills share (`app-patterns.md`, `app-design.md`, `ui-detection.md`). |
| `experience-app-objects` | skill | OOUX analysis from the code: objects, attribute homes, screens and editors the model implies, gaps against what the app has. |
| `experience-app-guideline` | skill | Adopts the P1–P17 rulebook into `APP-DESIGN.md` and checks the code against it. |
| `experience-app-interview` | skill | Interviews the owner area by area and records the answers in `APP-DESIGN.md`, including the `decide` rows of an `app-model` compare. |

## Use

```bash
skaile source add skaile-ai/ai-assets-app-explore
skaile add skill:@skaile-ai/app-explore skill:@skaile-ai/app-model
```

Then, in an agent session:

```text
app-explore <url> [sandbox] [since <path>|since auto] [seed <path>] [budget <n>]
app-model [<repo path>] [url <url>] [from <code,docs,app>] [explore <stem>.data] [map] [propose]
```

- Read-only by default: a guard in the page rejects writes (PUT, PATCH, DELETE, POST except GraphQL queries and allow-listed endpoints) and the crawler never presses delete, save, send or logout. `sandbox` allows writes for apps whose data may change; logout stays blocked.
- `since auto` builds on the newest previous report for the same host; `since <path>` names one.
- `budget <n>` caps the number of states (default 60).
- `seed <path>` starts the object model from an `app-model.docs.yaml` or `.code.yaml`: its objects keep their ids and its tasks are walked.

Requires `@skaile-ai/report` ≥ 0.6.0 (installed as a dependency) and omp's eval `browser`. Login walls are passed by borrowing the session from your Chrome through the omp browser relay, or by signing in once in a headed window.

## Files

| File | Job |
|---|---|
| `app-explore/app-explore/SKILL.md` | The steps the agent follows. |
| `app-explore/app-explore/crawl.mjs` | Browser helpers imported in an omp JavaScript eval cell: login handling, write guard, Set-of-Mark marks, DOM geometry checks, dHash, breadth-first crawl. |
| `app-explore/app-model/SKILL.md` | The app-model steps: extract sources, validate, align and compare, feature map. |
| `app-explore/app-model/*.py` | `model.py` (format, validate), `from_explore.py` (app source), `import_concept.py` (docs from `_concept/`), `compare.py` (align, merge, mismatch rules), `featuremap.py` (coverage, status, proposals). Run with `uv run --quiet --with pyyaml==6.0.3 python3`. |
| `app-explore/app-model/schema/app-model.schema.json` | JSON Schema of the app-model/1 format. |

`skaile.manifest.yaml` is the publish inventory; `skaile library index ai-assets-app-explore` keeps it in step with the files on disk.

## License

MIT, see [LICENSE](LICENSE).
