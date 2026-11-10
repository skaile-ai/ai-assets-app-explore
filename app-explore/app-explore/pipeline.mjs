// Perception, ontology synthesis and first-click scent for app-explore, run from an omp JavaScript eval cell.
//   const ap = await import(`${helpers}/pipeline.mjs`);   // helpers = this skill's dir, see SKILL.md
//   await ap.perceive({ judgeBatch, completion }, { dataDir });
//   await ap.synthesize({ completion }, { dataDir });
//   await ap.scent({ judgeBatch }, { dataDir });
// Module code cannot see eval prelude globals: the model helpers are passed in. Questions live in rubric.json.
import { readdir, readFile, writeFile } from 'node:fs/promises';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';
import { writeRun } from './crawl.mjs';

const RUBRIC = fileURLToPath(new URL('./rubric.json', import.meta.url));

const readJson = async (p) => JSON.parse(await readFile(p, 'utf8'));
const writeJson = (p, v) => writeFile(p, JSON.stringify(v, null, 2));

/** Graph, rubric, screens and the reports dir of a run. Media paths in graph.json are relative to the reports dir. */
async function load(dataDir, { screens = false } = {}) {
  const graph = await readJson(join(dataDir, 'graph.json'));
  const rubric = await readJson(RUBRIC);
  const reports = dirname(dataDir);
  const scr = {};
  if (screens) for (const s of graph.states) scr[s.id] = await readJson(join(dataDir, 'screens', `${s.id}.json`));
  return { graph, rubric, reports, screens: scr };
}

/** Run `fn` over `items` with at most `n` in flight; results in input order. */
async function pool(items, n, fn) {
  const out = new Array(items.length);
  let next = 0;
  await Promise.all(Array.from({ length: Math.min(n, items.length) }, async () => {
    while (next < items.length) { const i = next++; out[i] = await fn(items[i], i); }
  }));
  return out;
}

/** Structured completion with one retry; returns {value} or {error}. */
async function ask(completion, prompt, opts) {
  let err;
  for (let i = 0; i < 2; i++) {
    try { return { value: await (await completion(prompt, opts)).wait() }; } catch (e) { err = e; }
  }
  return { error: String(err?.message || err) };
}

/** Pull every settled item of a judge batch, then release it. Returns {key: item}. */
async function drainAll(batch) {
  const out = {};
  try {
    for (;;) {
      const got = await batch.drain(120);
      for (const [k, item] of got) out[k] = item;
      if (!got.length && !(await batch.status()).running) break;
    }
  } finally { await batch.close(); }
  return out;
}

const markLines = (marks, max = Infinity) => marks.slice(0, max).map((m) => `${m.n}: ${m.role} "${m.label}"`).join('\n');

// ---------------------------------------------------------------- perceive

const EXTRACT_SCHEMA = {
  type: 'object',
  properties: {
    purpose: { type: 'string' },
    objects: { type: 'array', items: { type: 'object', properties: {
      name: { type: 'string' },
      as: { type: 'string', enum: ['list', 'card', 'table', 'detail', 'form', 'chip', 'menu-item'] },
      attributes: { type: 'array', items: { type: 'string' } },
      count: { type: 'integer' },
    }, required: ['name', 'as', 'attributes', 'count'] } },
    actions: { type: 'array', items: { type: 'object', properties: {
      verb: { type: 'string' },
      object: { type: 'string' },
      mark: { type: ['integer', 'null'] },
      primary: { type: 'boolean' },
    }, required: ['verb', 'object', 'mark', 'primary'] } },
  },
  required: ['purpose', 'objects', 'actions'],
};

function extractPrompt(state, screen) {
  return `You read one screen of a web app as text: its numbered interactive elements (marks), its visible text and its accessibility tree. Report what a user perceives on it, in OOUX terms.

- purpose: one sentence, what a user does on this screen.
- objects: the domain things the user sees (projects, invoices, people …), never UI chrome (button, sidebar, search box). Use the name the screen uses. as = how it is shown (list, card, table, detail, form, chip, menu-item); attributes = the attribute names visible for it; count = how many instances are visible.
- actions: what a user can do here: verb, the object it acts on, the mark number of its control (null when no mark), primary = true only for the screen's main action.

Screen: ${state.kind} "${state.heading || state.title}" at ${state.url}

Marks:
${markLines(screen.marks)}

Visible text:
${screen.text}

Accessibility tree:
${screen.aria}`;
}

/**
 * Judge the rubric questions on every state's marked screenshot and extract objects/actions from its text with the
 * smol model, both in parallel. Writes <data>/perceive.json `{<id>: {answers, extract}}` and run.json `perception`.
 * Throws when no image-capable judge exists (then use the agent fallback in SKILL.md).
 */
export async function perceive({ judgeBatch, completion }, { dataDir, concurrency = 16, extractConcurrency = 8 }) {
  const t0 = Date.now();
  const { graph, rubric, reports, screens } = await load(dataDir, { screens: true });
  const states = {}, images = {};
  for (const s of graph.states) {
    states[s.id] = { title: s.title, heading: s.heading, url: s.url, purpose_hint: (screens[s.id].text || '').slice(0, 600) };
    images[s.id] = [join(reports, s.som)];
  }
  const judged = (async () => {
    const t = Date.now();
    try {
      const b = await judgeBatch(states, rubric.questions, { images, concurrency, intent: 'app-explore perceive' });
      return { items: await drainAll(b), ms: Date.now() - t };
    } catch (e) {
      // the run died wholesale, e.g. no image-capable judge: extraction still lands, answers come from agents
      return { items: {}, ms: Date.now() - t, error: String(e?.message || e) };
    }
  })();
  const extracted = (async () => {
    const t = Date.now();
    const out = await pool(graph.states, extractConcurrency, (s) =>
      ask(completion, extractPrompt(s, screens[s.id]), { model: 'smol', schema: EXTRACT_SCHEMA }));
    return { out, ms: Date.now() - t };
  })();
  const [j, x] = await Promise.all([judged, extracted]);
  const perceived = {};
  const failed = { judge: [], extract: [] };
  graph.states.forEach((s, i) => {
    const item = j.items[s.id];
    const e = x.out[i];
    if (!item?.ok) failed.judge.push(s.id);
    if (e.error) failed.extract.push(s.id);
    perceived[s.id] = {
      answers: item?.ok ? item.answers : null,
      extract: e.error ? null : e.value,
      ...(item?.ok ? {} : { judge_error: String(item?.error ?? 'not judged') }),
      ...(e.error ? { extract_error: e.error } : {}),
    };
  });
  await writeJson(join(dataDir, 'perceive.json'), perceived);
  await writeRun(dataDir, { perception: j.error ? 'pending' : 'judge' });
  return {
    states: graph.states.length, failed, judge_ms: j.ms, extract_ms: x.ms, ms: Date.now() - t0,
    ...(j.error ? { judge_error: j.error } : {}),
  };
}

/**
 * Judge fallback: merge agent-written answers `<data>/perceive.agent/<batch>.json` (`{<state id>: {<question id>:
 * judge-shaped answer}}`) into perceive.json and set run.json `perception: "agent"`. Returns the states still unanswered.
 */
export async function mergeAgentAnswers({ dataDir }) {
  const perceived = await readJson(join(dataDir, 'perceive.json'));
  const dir = join(dataDir, 'perceive.agent');
  for (const f of (await readdir(dir)).filter((n) => n.endsWith('.json')).sort()) {
    for (const [id, answers] of Object.entries(await readJson(join(dir, f)))) {
      if (!perceived[id]) continue;
      perceived[id].answers = answers;
      delete perceived[id].judge_error;
    }
  }
  await writeJson(join(dataDir, 'perceive.json'), perceived);
  await writeRun(dataDir, { perception: 'agent' });
  return Object.keys(perceived).filter((id) => !perceived[id].answers);
}

// ---------------------------------------------------------------- synthesize

const MODEL_SCHEMA = {
  type: 'object',
  properties: {
    personas: { type: 'array', items: { type: 'object', properties: {
      id: { type: 'string' }, name: { type: 'string' }, goal: { type: 'string' },
    }, required: ['id', 'name', 'goal'] } },
    objects: { type: 'array', items: { type: 'object', properties: {
      id: { type: 'string' },
      name: { type: 'string' },
      aliases: { type: 'array', items: { type: 'string' } },
      class: { type: 'string', enum: ['core', 'supporting', 'child', 'system'] },
      attributes: { type: 'array', items: { type: 'string' } },
      relationships: { type: 'array', items: { type: 'object', properties: {
        to: { type: 'string' }, as: { type: 'string' },
      }, required: ['to', 'as'] } },
      ctas: { type: 'array', items: { type: 'object', properties: {
        verb: { type: 'string' }, states: { type: 'array', items: { type: 'string' } },
      }, required: ['verb', 'states'] } },
      homes: { type: 'array', items: { type: 'string' } },
      representations: { type: 'array', items: { type: 'object', properties: {
        state: { type: 'string' },
        as: { type: 'string', enum: ['list', 'card', 'table', 'detail', 'form', 'chip', 'menu-item'] },
      }, required: ['state', 'as'] } },
    }, required: ['id', 'name', 'aliases', 'class', 'attributes', 'relationships', 'ctas', 'homes', 'representations'] } },
    tasks: { type: 'array', items: { type: 'object', properties: {
      id: { type: 'string' }, title: { type: 'string' }, persona: { type: 'string' },
      object: { type: 'string' }, verb: { type: 'string' }, target_state: { type: 'string' },
    }, required: ['id', 'title', 'persona', 'object', 'verb', 'target_state'] } },
  },
  required: ['personas', 'objects', 'tasks'],
};

function synthPrompt(graph, perceived, lang, prev) {
  const states = graph.states.map((s) => ({
    id: s.id, route: s.route, kind: s.kind, heading: s.heading, depth: s.depth,
    purpose: perceived[s.id]?.extract?.purpose ?? null,
    objects: perceived[s.id]?.extract?.objects ?? [],
    actions: perceived[s.id]?.extract?.actions ?? [],
  }));
  const edges = graph.edges.map((e) => `${e.from} -> ${e.to} "${e.label ?? ''}"`).join('\n');
  return `You build the object model a user perceives in a web app (OOUX ORCA: objects, relationships, calls to action, attributes), from per-screen extractions of a crawl.

Rules:
- Merge synonyms: when screens call the same thing by different names, make one object and list every other name the UI uses for it in \`aliases\` (exact UI wording). \`aliases\` excludes \`name\` and its plural or case variants; a person's or item's own name (an instance) is never an alias.
- class: core = has its own navigation entry and an index (list) screen; supporting = shown inside core objects with its own screens or detail; child = only exists inside one parent; system = generated by the app (logs, notifications, status).
- Ignore UI chrome (buttons, sidebars, search boxes, the app itself).
- homes: the state ids where the object is primarily listed or shown. representations: every state where it appears and how (list, card, table, detail, form, chip, menu-item). ctas: verbs a user can do to it and the state ids where that control sits. relationships: other object ids and the relation ("has many", "belongs to" …).
- personas: exactly 2: id "p1" = "first-time user" (goal: find their way around), id "p2" = one domain role you infer from the app.
- tasks: at most 6, ids t1…t6, favouring create, find and edit of core objects; persona = a persona id; object = an object id; target_state = the existing state id where the task is done (for create/edit: where its form opens).
- Every state id you use must be one of the state ids below. Object ids: lowercase slugs.
- Write names, goals and task titles in the app's UI language (${lang}).
${prev ? `\nA previous run of this app produced the model below. Its state ids belong to the previous crawl and mean nothing here: take every state id from the states below. Keep its persona and object ids for the same things. Keep every previous task with its id, persona and title, pick its target_state among the states below, and drop it only when no state below lets a user do it; new tasks get the next free ids (at most 2 new tasks; the 6-task cap does not apply to kept tasks). New things get new ids.\n${JSON.stringify(prev)}\n` : ''}
States (crawl order, depth = clicks from the start):
${JSON.stringify(states)}

Edges (from -> to "control"):
${edges}`;
}

/**
 * Synthesise personas, objects and tasks across all screens with the slow model. Writes <data>/model.json after
 * dropping objects without a `homes` state in graph.json and tasks whose `target_state` is missing.
 * `prev` = a previous run's model.json (keeps ids stable); by default read from run.json `since` (the previous
 * run's data dir). Its state references are stripped before prompting. `kept.missing` lists previous task ids the
 * new model lost.
 */
export async function synthesize({ completion }, { dataDir, prev = undefined }) {
  const t0 = Date.now();
  const { graph } = await load(dataDir);
  const perceived = await readJson(join(dataDir, 'perceive.json'));
  let run = {};
  try { run = await readJson(join(dataDir, 'run.json')); } catch {}
  if (prev === undefined) prev = run.since ? await readJson(join(run.since, 'model.json')).catch(() => null) : null;
  const brief = prev && {
    personas: prev.personas,
    objects: prev.objects.map(({ id, name, aliases, class: cls }) => ({ id, name, aliases, class: cls })),
    tasks: prev.tasks.map(({ id, title, persona, object, verb }) => ({ id, title, persona, object, verb })),
  };
  const r = await ask(completion, synthPrompt(graph, perceived, run.lang || 'en', brief), { model: 'slow', schema: MODEL_SCHEMA });
  if (r.error) throw new Error(`synthesize: ${r.error}`);
  const m = r.value;
  const ids = new Set(graph.states.map((s) => s.id));
  const before = { objects: m.objects.length, tasks: m.tasks.length };
  for (const o of m.objects) {
    o.homes = o.homes.filter((h) => ids.has(h));
    o.representations = o.representations.filter((x) => ids.has(x.state));
    o.ctas = o.ctas.map((c) => ({ ...c, states: c.states.filter((s) => ids.has(s)) }));
    o.aliases = [...new Set(o.aliases.filter((a) => a && !sameWord(a, o.name)))];
  }
  m.objects = m.objects.filter((o) => o.homes.length);
  const objIds = new Set(m.objects.map((o) => o.id));
  for (const o of m.objects) o.relationships = o.relationships.filter((x) => objIds.has(x.to));
  m.tasks = m.tasks.filter((t) => ids.has(t.target_state));
  await writeJson(join(dataDir, 'model.json'), m);
  const taskIds = new Set(m.tasks.map((t) => t.id));
  return {
    personas: m.personas.length, objects: m.objects.length, tasks: m.tasks.length,
    dropped: { objects: before.objects - m.objects.length, tasks: before.tasks - m.tasks.length },
    kept: prev ? { tasks: prev.tasks.filter((t) => taskIds.has(t.id)).length, missing: prev.tasks.filter((t) => !taskIds.has(t.id)).map((t) => t.id) } : null,
    ms: Date.now() - t0,
  };
}

// ---------------------------------------------------------------- scent

/** Click distance of every state to `target` over graph edges (reverse BFS). */
function distTo(graph, target) {
  const back = {};
  for (const e of graph.edges) (back[e.to] ||= []).push(e.from);
  const d = { [target]: 0 };
  const q = [target];
  while (q.length) {
    const n = q.shift();
    for (const p of back[n] || []) if (!(p in d)) { d[p] = d[n] + 1; q.push(p); }
  }
  return d;
}

const norm = (s) => String(s ?? '').replace(/\s+/g, ' ').trim().toLowerCase();

/** Same word up to case and a plural ending (s, es, en, n, e): not a second name for an object. */
function sameWord(a, b) {
  const [x, y] = [norm(a), norm(b)].sort((p, q) => p.length - q.length);
  return x === y || (y.startsWith(x) && /^(s|es|en|n|e)$/.test(y.slice(x.length)));
}

/**
 * Mark number of an edge on the entry screen: the recorded mark, else the mark whose label matches the edge label,
 * else the link mark whose href is the target state's url.
 */
function edgeMark(edge, marks, targetUrl) {
  if (edge.mark != null) return edge.mark;
  const l = norm(edge.label);
  const strip = (u) => String(u).replace(/#.*$/, '');
  const hit = (l && (marks.find((m) => norm(m.label) === l)
    || marks.find((m) => norm(m.label) && (l.startsWith(norm(m.label)) || norm(m.label).startsWith(l)))))
    || (targetUrl && marks.find((m) => m.href && strip(m.href) === strip(targetUrl)));
  return hit ? hit.n : null;
}

/**
 * Per task: which mark on the entry state (the crawl's first state) would the persona click first? Compared with
 * the first edge of the shortest click path from the entry to the task's target_state. Writes <data>/scent.json.
 * Judge fallback: `answers` = `{<task id>: {choice, probabilities, confidence}}` written by an agent skips the judge.
 * When the judge dies wholesale, <data>/scent.questions.json gets the per-task states and the question, then it throws.
 */
export async function scent({ judgeBatch }, { dataDir, concurrency = 16, answers = null }) {
  const t0 = Date.now();
  const { graph, rubric, reports } = await load(dataDir);
  const model = await readJson(join(dataDir, 'model.json'));
  const entry = graph.states[0];
  const screen = await readJson(join(dataDir, 'screens', `${entry.id}.json`));
  const marks = screen.marks.slice(0, rubric.scent.max_marks);
  const personas = Object.fromEntries(model.personas.map((p) => [p.id, p]));
  const out = {};
  if (!model.tasks.length || marks.length < 2) {
    await writeJson(join(dataDir, 'scent.json'), out);
    return { tasks: 0, ms: Date.now() - t0 };
  }
  const states = {}, images = {};
  for (const t of model.tasks) {
    const p = personas[t.persona];
    states[t.id] = {
      persona: p ? `${p.name}: ${p.goal}` : t.persona,
      task: t.title,
      screen: entry.heading || entry.title,
      marks: markLines(marks),
    };
    images[t.id] = [join(reports, entry.som)];
  }
  const criteria = Object.fromEntries(marks.map((m) => [String(m.n), `${m.role} "${m.label}"`]));
  const question = { first_click: { type: 'choice', instructions: rubric.scent.instructions, criteria } };
  let items;
  if (answers) {
    items = Object.fromEntries(Object.entries(answers).map(([k, a]) => [k, { ok: true, answers: { first_click: a } }]));
  } else {
    try {
      items = await drainAll(await judgeBatch(states, question, { images, concurrency, intent: 'app-explore scent' }));
    } catch (e) {
      await writeJson(join(dataDir, 'scent.questions.json'), { image: join(reports, entry.som), question, states });
      throw new Error(`scent: judge unavailable (${e?.message || e}); questions in scent.questions.json`);
    }
  }
  const fromEntry = graph.edges.filter((e) => e.from === entry.id);
  const urlOf = Object.fromEntries(graph.states.map((s) => [s.id, s.url]));
  for (const t of model.tasks) {
    const a = items[t.id]?.ok ? items[t.id].answers.first_click : null;
    const d = distTo(graph, t.target_state);
    const clicks = d[entry.id] ?? null;
    const firstEdges = clicks ? fromEntry.filter((e) => d[e.to] === clicks - 1) : [];
    const firsts = [...new Set(firstEdges.map((e) => edgeMark(e, screen.marks, urlOf[e.to])).filter((n) => n != null))];
    const predicted = a ? Number(a.choice) : null;
    out[t.id] = {
      entry: entry.id,
      predicted_mark: predicted,
      p: a ? a.probabilities?.[a.choice] ?? a.confidence ?? null : null,
      shortest_first_mark: firsts[0] ?? null,
      first_marks: firsts,
      first_labels: [...new Set(firstEdges.map((e) => e.label).filter(Boolean))],
      clicks,
      // null: no prediction, target is the entry itself, or unreachable. A path whose first control has no mark on
      // the entry screenshot (e.g. below the fold) counts as a miss: the persona cannot pick it.
      correct: predicted == null || !clicks ? null : firsts.includes(predicted),
      ...(a ? {} : { error: String(items[t.id]?.error ?? 'not judged') }),
    };
  }
  await writeJson(join(dataDir, 'scent.json'), out);
  return { tasks: model.tasks.length, ms: Date.now() - t0 };
}
