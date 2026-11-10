// Perception, ontology synthesis, synonym checks and first-click scent for app-explore, run from an omp JavaScript eval cell.
//   const ap = await import(`${helpers}/pipeline.mjs`);   // helpers = this skill's dir, see SKILL.md
//   await ap.perceive({ judgeBatch, completion }, { dataDir });
//   await ap.synthesize({ completion }, { dataDir });
//   await ap.synonyms({ judgeBatch }, { dataDir });
//   await ap.scent({ judgeBatch }, { dataDir });
//   await ap.pathScent({ judgeBatch }, { dataDir });    // features.scent_path: scent along each task's shortest path
//   const brief = await ap.criticBrief({ dataDir, states, batch: 'c1' });   // step 8 critic prompt; features.examples
//   await ap.mentalModel({ judgeBatch, completion }, { dataDir [, pass: 'walks'] });  // features.mental_model (mental.mjs)
// Module code cannot see eval prelude globals: the model helpers are passed in. Questions live in rubric.json, and so
// does each call kind's model role (`models`); every call is counted into run.json `models` (config.mjs `meter`).
import { readdir, readFile, writeFile } from 'node:fs/promises';
import { dirname, join } from 'node:path';
import { writeRun } from './crawl.mjs';
import { features, meter, readRubric } from './config.mjs';
export { mentalModel } from './mental.mjs';

const readJson = async (p) => JSON.parse(await readFile(p, 'utf8'));
const writeJson = (p, v) => writeFile(p, JSON.stringify(v, null, 2));

/** Graph, rubric, screens and the reports dir of a run. Media paths in graph.json are relative to the reports dir. */
export async function load(dataDir, { screens = false } = {}) {
  const graph = await readJson(join(dataDir, 'graph.json'));
  const rubric = await readRubric();
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

/** Structured completion of call kind `kind` with one retry (each attempt counted); returns {value} or {error}. */
export async function ask(mt, completion, kind, prompt, opts) {
  let err;
  for (let i = 0; i < 2; i++) {
    try { return { value: await mt.complete(completion, kind, prompt, opts) }; } catch (e) { err = e; }
  }
  return { error: String(err?.message || err) };
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
  const mt = meter(dataDir, rubric);
  const states = {}, images = {};
  for (const s of graph.states) {
    states[s.id] = { title: s.title, heading: s.heading, url: s.url, purpose_hint: (screens[s.id].text || '').slice(0, 600) };
    images[s.id] = [join(reports, s.som)];
  }
  const judged = (async () => {
    const t = Date.now();
    try {
      const items = await mt.judge(judgeBatch, 'perceive_judge', states, rubric.questions, { images, concurrency, intent: 'app-explore perceive' });
      return { items, ms: Date.now() - t };
    } catch (e) {
      // the run died wholesale, e.g. no image-capable judge: extraction still lands, answers come from agents
      return { items: {}, ms: Date.now() - t, error: String(e?.message || e) };
    }
  })();
  const extracted = (async () => {
    const t = Date.now();
    const out = await pool(graph.states, extractConcurrency, (s) =>
      ask(mt, completion, 'extract', extractPrompt(s, screens[s.id]), { schema: EXTRACT_SCHEMA }));
    return { out, ms: Date.now() - t };
  })();
  const [j, x] = await Promise.all([judged, extracted]);
  await mt.flush();
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
      object: { type: 'string' }, verb: { type: 'string' }, target_state: { type: ['string', 'null'] },
    }, required: ['id', 'title', 'persona', 'object', 'verb', 'target_state'] } },
  },
  required: ['personas', 'objects', 'tasks'],
};

/** MODEL_SCHEMA with `variants` per persona (feature `personas` > 1; rubric.json `personas` names the values). */
function variantSchema(P) {
  const variant = { type: 'object', properties: {
    id: { type: 'string' }, name: { type: 'string' },
    literacy: { type: 'string', enum: P.literacy }, hurry: { type: 'boolean' },
    domain: { type: 'string', enum: P.domain }, note: { type: 'string' },
  }, required: ['id', 'name', 'literacy', 'hurry', 'domain', 'note'] };
  const persona = MODEL_SCHEMA.properties.personas.items;
  return { ...MODEL_SCHEMA, properties: { ...MODEL_SCHEMA.properties, personas: { type: 'array', items: {
    ...persona, properties: { ...persona.properties, variants: { type: 'array', items: variant } },
    required: [...persona.required, 'variants'] } } } };
}

const variantRule = (n, P) => `- variants (each persona): exactly ${n}, ids "<persona id>-v1" … "<persona id>-v${n}"; name = a short label of the person (e.g. "hurried expert"); literacy ${P.literacy.join(' | ')}; hurry true or false; domain = prior domain knowledge ${P.domain.join(' | ')}; note = one sentence on how this person approaches the app; name and note in the app's UI language. ${P.variant_text}\n`;

/**
 * Feature `personas` > 1: each persona keeps at most `n` variants with unique file-safe ids (`<persona id>-v<k>` when
 * the model's id is unusable). Returns the persona ids that got fewer than `n`.
 */
function normaliseVariants(personas, n) {
  const short = [];
  for (const p of personas) {
    const seen = new Set();
    p.variants = (Array.isArray(p.variants) ? p.variants : []).slice(0, n).map((v, k) => {
      let id = String(v.id ?? '').toLowerCase().replace(/[^a-z0-9-]+/g, '-');
      if (!id.startsWith(`${p.id}-`) || seen.has(id)) id = `${p.id}-v${k + 1}`;
      seen.add(id);
      return { ...v, id };
    });
    if (p.variants.length < n) short.push(p.id);
  }
  return short;
}

function synthPrompt(graph, perceived, lang, prev, variants = 0, P = null) {
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
${variants ? variantRule(variants, P) : ''}- tasks: at most 6, ids t1…t6, favouring create, find and edit of core objects; persona = a persona id; object = an object id; target_state = the existing state id where the task is done (for create/edit: where its form opens).
- Every state id you use must be one of the state ids below. Object ids: lowercase slugs.
- Write names, goals and task titles in the app's UI language (${lang}).
${prev ? `\nA previous run of this app produced the model below. Its state ids belong to the previous crawl and mean nothing here: take every state id from the states below. Keep its persona and object ids for the same things. Its tasks are kept as they are: do not list them again. Add at most 2 new tasks with the next free ids (the 6-task cap does not count the previous tasks). New things get new ids.\n${JSON.stringify(prev)}\n` : ''}
States (crawl order, depth = clicks from the start):
${JSON.stringify(states)}

Edges (from -> to "control"):
${edges}`;
}

/**
 * {previous state id: current state id}, one to one: by state key, else by route + kind + heading (analyze.py's
 * screen match for diff.json).
 */
function matchStates(prevStates, states) {
  const out = {};
  const used = new Set();
  for (const sig of [(s) => s.key, (s) => `${s.route}|${s.kind}|${norm(s.heading)}`]) {
    const index = new Map();
    for (const p of prevStates) if (!Object.hasOwn(out, p.id)) index.set(sig(p), [...(index.get(sig(p)) ?? []), p.id]);
    for (const s of states) {
      if (used.has(s.id)) continue;
      const pid = (index.get(sig(s)) ?? []).find((p) => !Object.hasOwn(out, p));
      if (pid) { out[pid] = s.id; used.add(s.id); }
    }
  }
  return out;
}

/**
 * Synthesise personas, objects and tasks across all screens with the slow model. Writes <data>/model.json after
 * dropping objects without a `homes` state in graph.json and new tasks whose `target_state` is missing.
 * `prev` = a previous run's model.json (keeps ids stable); by default read from run.json `since` (the previous
 * run's data dir). Its state references are stripped before prompting. Every previous task stays in the model so it
 * is walked again, and its target is never the model's pick: it is the current state matching its previous target
 * (by state key, else route + kind + heading, as diff.json matches screens), else `null` with
 * `target_missing: true`. model.json `kept` = `{ids, missing}`: the previous task ids and those without a target.
 * Feature `personas` n > 1: every persona also gets `variants` (n-1, rubric.json `personas`: `{id, name, literacy,
 * hurry, domain, note}`, id `<persona id>-v<k>`), the people of the kernel walks (walk.mjs `walkAll`); the result
 * then has `variants` (count) and `variants_short` (persona ids with fewer). n = 1: prompt and schema as without it.
 */
export async function synthesize({ completion }, { dataDir, prev = undefined }) {
  const t0 = Date.now();
  const { graph, rubric } = await load(dataDir);
  const mt = meter(dataDir, rubric);
  const perceived = await readJson(join(dataDir, 'perceive.json'));
  let run = {};
  try { run = await readJson(join(dataDir, 'run.json')); } catch {}
  if (prev === undefined) prev = run.since ? await readJson(join(run.since, 'model.json')).catch(() => null) : null;
  const prevGraph = prev && run.since ? await readJson(join(run.since, 'graph.json')).catch(() => null) : null;
  const nv = Math.max(0, ((await features(dataDir)).personas ?? 1) - 1);
  const brief = prev && {
    personas: nv ? prev.personas : prev.personas.map(({ variants: _, ...p }) => p),
    objects: prev.objects.map(({ id, name, aliases, class: cls }) => ({ id, name, aliases, class: cls })),
    tasks: prev.tasks.map(({ id, title, persona, object, verb }) => ({ id, title, persona, object, verb })),
  };
  const r = await ask(mt, completion, 'synthesize', synthPrompt(graph, perceived, run.lang || 'en', brief, nv, rubric.personas),
    { schema: nv ? variantSchema(rubric.personas) : MODEL_SCHEMA });
  await mt.flush();
  if (r.error) throw new Error(`synthesize: ${r.error}`);
  const m = r.value;
  if (!nv) for (const p of m.personas) delete p.variants;
  const short = nv ? normaliseVariants(m.personas, nv) : [];
  const ids = new Set(graph.states.map((s) => s.id));
  const before = { objects: m.objects.length };
  for (const o of m.objects) {
    o.homes = o.homes.filter((h) => ids.has(h));
    o.representations = o.representations.filter((x) => ids.has(x.state));
    o.ctas = o.ctas.map((c) => ({ ...c, states: c.states.filter((s) => ids.has(s)) }));
    o.aliases = [...new Set(o.aliases.filter((a) => a && !sameWord(a, o.name)))];
  }
  m.objects = m.objects.filter((o) => o.homes.length);
  const objIds = new Set(m.objects.map((o) => o.id));
  for (const o of m.objects) o.relationships = o.relationships.filter((x) => objIds.has(x.to));
  const prevIds = new Set(prev ? prev.tasks.map((t) => t.id) : []);
  const fresh = m.tasks.filter((t) => !prevIds.has(t.id));
  const lost = fresh.filter((t) => !ids.has(t.target_state)).length;
  m.tasks = fresh.filter((t) => ids.has(t.target_state));
  if (prev) {
    const now = prevGraph ? matchStates(prevGraph.states, graph.states) : {};
    const kept = prev.tasks.map(({ target_missing: _, ...p }) => {
      const target = now[p.target_state] ?? null;
      return { ...p, target_state: target, ...(target ? {} : { target_missing: true }) };
    });
    m.tasks = [...kept, ...m.tasks];
    m.kept = { ids: kept.map((t) => t.id), missing: kept.filter((t) => t.target_missing).map((t) => t.id) };
  }
  await writeJson(join(dataDir, 'model.json'), m);
  return {
    personas: m.personas.length, objects: m.objects.length, tasks: m.tasks.length,
    ...(nv ? { variants: m.personas.reduce((a, p) => a + p.variants.length, 0), variants_short: short } : {}),
    dropped: { objects: before.objects - m.objects.length, tasks: lost },
    kept: m.kept ?? null,
    ms: Date.now() - t0,
  };
}

// ---------------------------------------------------------------- synonyms

const tokens = (s) => new Set(norm(s).split(/[^\p{L}\p{N}]+/u).filter((w) => w.length >= 3));
const sharesToken = (a, b) => { const x = tokens(a); return [...tokens(b)].some((w) => x.has(w)); };

/**
 * Cheap-judge check of names the naming rule would otherwise take on the slow model's word: per pair "do both name
 * the same thing?" (rubric.json `synonyms`, a bool question under the gate). Candidate pairs, in this order, capped at
 * `synonyms.max_pairs`: `alias` (an object's name and each alias synthesize gave it), `objects` (two objects whose
 * names share a word of 3+ letters), `label` (an object name the per-screen extraction used that is no model name or
 * alias, and an object's name sharing a word with it). Writes <data>/synonyms.json `[{id, kind, object, other, a, b,
 * states_a, states_b, answer}]` (`answer` `{bool}`, null when unjudged); analyze.py's naming rule reads it. A judge
 * that dies wholesale leaves every answer null and returns `judge_error`: naming then rests on the model alone.
 */
export async function synonyms({ judgeBatch }, { dataDir, concurrency = 16 }) {
  const t0 = Date.now();
  const { graph, rubric } = await load(dataDir);
  const model = await readJson(join(dataDir, 'model.json'));
  const perceived = await readJson(join(dataDir, 'perceive.json'));
  const screenName = Object.fromEntries(graph.states.map((s) => [s.id, s.heading || s.title || s.id]));
  const seen = new Map(); // normalized extracted object name → {label, states}
  for (const s of graph.states) {
    for (const o of perceived[s.id]?.extract?.objects ?? []) {
      const k = norm(o.name);
      if (!k) continue;
      if (!seen.has(k)) seen.set(k, { label: o.name, states: new Set() });
      seen.get(k).states.add(s.id);
    }
  }
  const where = (label, fallback = []) => [...(seen.get(norm(label))?.states ?? fallback)];
  const pairs = [];
  const add = (p) => {
    if (sameWord(p.a, p.b)) return;
    if (pairs.some((q) => (sameWord(q.a, p.a) && sameWord(q.b, p.b)) || (sameWord(q.a, p.b) && sameWord(q.b, p.a)))) return;
    pairs.push(p);
  };
  for (const o of model.objects) {
    for (const al of o.aliases) add({ kind: 'alias', object: o.id, other: null, a: o.name, b: al, states_a: where(o.name, o.homes), states_b: where(al) });
  }
  model.objects.forEach((o, i) => {
    for (const p of model.objects.slice(i + 1)) {
      if (sharesToken(o.name, p.name)) add({ kind: 'objects', object: o.id, other: p.id, a: o.name, b: p.name, states_a: where(o.name, o.homes), states_b: where(p.name, p.homes) });
    }
  });
  const known = model.objects.flatMap((o) => [o.name, ...o.aliases]);
  for (const { label, states } of seen.values()) {
    if (known.some((k) => sameWord(k, label))) continue;
    for (const o of model.objects) {
      if (sharesToken(o.name, label)) add({ kind: 'label', object: o.id, other: null, a: o.name, b: label, states_a: where(o.name, o.homes), states_b: [...states] });
    }
  }
  const list = pairs.slice(0, rubric.synonyms.max_pairs).map((p, i) => ({ id: `y${i + 1}`, ...p }));
  const screens = (ids) => ids.slice(0, 6).map((id) => screenName[id] ?? id);
  const states = Object.fromEntries(list.map((p) => [p.id, { a: p.a, a_screens: screens(p.states_a), b: p.b, b_screens: screens(p.states_b) }]));
  const question = { same: { type: rubric.synonyms.type, instructions: rubric.synonyms.instructions } };
  let items = {}, error = null;
  if (list.length) {
    const mt = meter(dataDir, rubric);
    try {
      items = await mt.judge(judgeBatch, 'synonyms', states, question, { concurrency, intent: 'app-explore synonyms' });
    } catch (e) { error = String(e?.message || e); }
    await mt.flush();
  }
  const out = list.map((p) => ({ ...p, answer: items[p.id]?.ok ? items[p.id].answers.same : null }));
  await writeJson(join(dataDir, 'synonyms.json'), out);
  return {
    pairs: out.length, candidates: pairs.length, judged: out.filter((p) => p.answer).length, ms: Date.now() - t0,
    ...(error ? { judge_error: error } : {}),
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

export const norm = (s) => String(s ?? '').replace(/\s+/g, ' ').trim().toLowerCase();

/** Same word up to case and a plural ending (s, es, en, n, e): not a second name for an object. */
export function sameWord(a, b) {
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
    const mt = meter(dataDir, rubric);
    try {
      items = await mt.judge(judgeBatch, 'scent', states, question, { images, concurrency, intent: 'app-explore scent' });
    } catch (e) {
      await writeJson(join(dataDir, 'scent.questions.json'), { image: join(reports, entry.som), question, states });
      throw new Error(`scent: judge unavailable (${e?.message || e}); questions in scent.questions.json`);
    } finally { await mt.flush(); }
  }
  const fromEntry = graph.edges.filter((e) => e.from === entry.id);
  const urlOf = Object.fromEntries(graph.states.map((s) => [s.id, s.url]));
  const offered = new Set(marks.map((m) => m.n));
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
      // null: no prediction, target is the entry itself, unreachable, or every first control of the path has a mark
      // the judge was not offered (beyond max_marks). A path whose first control has no mark on the entry screenshot
      // at all (e.g. below the fold) counts as a miss: the persona cannot pick it.
      correct: predicted == null || !clicks || (firsts.length && !firsts.some((n) => offered.has(n))) ? null
        : firsts.includes(predicted),
      ...(a ? {} : { error: String(items[t.id]?.error ?? 'not judged') }),
    };
  }
  await writeJson(join(dataDir, 'scent.json'), out);
  return { tasks: model.tasks.length, ms: Date.now() - t0 };
}

// ---------------------------------------------------------------- path scent (features.scent_path)

/**
 * Marks in reading order: rows top to bottom, left to right within a row. A mark joins the current row when its top
 * edge is less than one typical mark height (the median) below the row's first mark, so a full-height rail or a tall
 * card does not swallow the rows beside it.
 */
function readingOrder(marks) {
  const box = (m) => m.box ?? { x: 0, y: 0, w: 0, h: 0 };
  const hs = marks.map((m) => box(m).h).sort((a, b) => a - b);
  const line = hs[Math.floor(hs.length / 2)] ?? 0;
  const rows = [];
  for (const m of [...marks].sort((a, b) => box(a).y - box(b).y || box(a).x - box(b).x)) {
    const row = rows.at(-1);
    if (row && box(m).y - row.top < line) row.marks.push(m);
    else rows.push({ top: box(m).y, marks: [m] });
  }
  return rows.flatMap((r) => r.marks.sort((a, b) => box(a).x - box(b).x));
}

/** The judge's pick among a chunk's `n` letters or `next`: probabilities renormalised over the labels it may give. */
function chunkPick(answer, letters, n) {
  const valid = [...letters.slice(0, n), 'next'];
  const probs = answer?.probabilities ?? {};
  const sum = valid.reduce((s, l) => s + (probs[l] ?? 0), 0);
  if (sum > 0) {
    const best = valid.reduce((a, b) => ((probs[b] ?? 0) > (probs[a] ?? 0) ? b : a));
    return { label: best, p: Math.round(((probs[best] ?? 0) / sum) * 100) / 100 };
  }
  return valid.includes(answer?.choice) ? { label: answer.choice, p: answer.confidence ?? null } : null;
}

/**
 * Sequential first-click scent along each task's shortest path (rubric.json `features.scent_path`; off: returns
 * {skipped}). Per path state, from the entry to the state before the task's target_state, the judge sees the
 * state's marks in reading order, `scent.chunk_size` at a time (capped at `scent.max_marks`), and picks one of the
 * chunk's lettered marks or `next`; `next` shows the following chunk in the next round. Every call is a judge call
 * of kind `path_scent`. Adds `steps[]` to each task of <data>/scent.json (run `scent` first): per path state
 * `{step, state, chunk, chunks, predicted, expected, expected_chunk, correct, premature, p}`; `predicted: null` means
 * `next` on the last chunk (nothing here looks right). `correct` is null when the judge gave no answer or every
 * expected control has a mark beyond the cap; false when the path's control has no mark at all. `premature`: a wrong
 * pick in a chunk before the one holding the right mark.
 */
export async function pathScent({ judgeBatch }, { dataDir, concurrency = 16 }) {
  const t0 = Date.now();
  if (!(await features(dataDir)).scent_path) return { skipped: true };
  const { graph, rubric, reports } = await load(dataDir);
  const model = await readJson(join(dataDir, 'model.json'));
  const out = await readJson(join(dataDir, 'scent.json'));
  const { chunk_size: size, max_marks: cap, path_instructions: instructions } = rubric.scent;
  const letters = 'ABCDEFGHIJKLMNOPQRSTUVWXYZ'.slice(0, size).split('');
  const entry = graph.states[0];
  const byId = Object.fromEntries(graph.states.map((s) => [s.id, s]));
  const personas = Object.fromEntries(model.personas.map((p) => [p.id, p]));
  const screens = {};
  const screenOf = async (id) => (screens[id] ??= await readJson(join(dataDir, 'screens', `${id}.json`)));
  const records = [];
  for (const t of model.tasks) {
    if (!out[t.id]) continue;
    const d = t.target_state ? distTo(graph, t.target_state) : {};
    const steps = (out[t.id].steps = []);
    const clicked = [];
    const n = d[entry.id] ?? 0;
    for (let cur = entry.id, i = 0; d[cur] > 0; i++) {
      const screen = await screenOf(cur);
      const order = readingOrder(screen.marks ?? []).slice(0, cap);
      const chunks = Array.from({ length: Math.ceil(order.length / size) }, (_, c) => order.slice(c * size, (c + 1) * size));
      const nextEdges = graph.edges.filter((e) => e.from === cur && d[e.to] === d[cur] - 1);
      const markOf = (e) => edgeMark(e, screen.marks ?? [], byId[e.to]?.url);
      const expected = [...new Set(nextEdges.map(markOf).filter((m) => m != null))];
      const at = chunks.findIndex((ch) => ch.some((m) => expected.includes(m.n)));
      const step = { step: i, state: cur, chunk: null, chunks: chunks.length, predicted: null, expected,
        expected_chunk: at < 0 ? null : at + 1, correct: null, premature: false, p: null };
      steps.push(step);
      const p = personas[t.persona];
      const base = {
        persona: p ? `${p.name}: ${p.goal}` : t.persona, task: t.title,
        screen: byId[cur].heading || byId[cur].title, step: `${i + 1} of ${n}`, clicked_so_far: [...clicked],
      };
      if (chunks.length) records.push({ key: `${t.id}:${i}`, step, chunks, base, som: byId[cur].som, c: 0 });
      else step.error = 'no marks';
      const via = nextEdges.find((e) => markOf(e) != null) ?? nextEdges[0];
      clicked.push(via.label || `mark ${via.mark ?? '?'}`);
      cur = via.to;
    }
  }
  const question = {
    pick: { type: 'choice', instructions, criteria: {
      ...Object.fromEntries(letters.map((l) => [l, `the mark listed as ${l}`])),
      next: 'none of the listed marks; read on (on the last group: click nothing here)',
    } },
  };
  const finish = (r, label, p) => {
    const s = r.step;
    s.chunk = r.c + 1;
    s.predicted = label === 'next' ? null : r.chunks[r.c][letters.indexOf(label)].n;
    s.p = p;
    s.correct = s.expected.length && s.expected_chunk == null ? null
      : s.predicted != null && s.expected.includes(s.predicted);
    s.premature = s.correct === false && s.predicted != null && s.expected_chunk != null && s.chunk < s.expected_chunk;
  };
  let pending = records, error = null, rounds = 0;
  const mt = meter(dataDir, rubric);
  try {
    while (pending.length) {
      rounds++;
      const states = {}, images = {};
      for (const r of pending) {
        const ch = r.chunks[r.c];
        states[r.key] = {
          ...r.base,
          marks: ch.map((m, j) => `${letters[j]} = mark ${m.n}: ${m.role} "${m.label}"`).join('\n'),
          more_marks_after_this: r.c + 1 < r.chunks.length,
        };
        images[r.key] = [join(reports, r.som)];
      }
      const items = await mt.judge(judgeBatch, 'path_scent', states, question,
        { images, concurrency, intent: `app-explore path scent, group ${rounds}` });
      const next = [];
      for (const r of pending) {
        const it = items[r.key];
        const pick = it?.ok ? chunkPick(it.answers.pick, letters, r.chunks[r.c].length) : null;
        if (!pick) { r.step.error = String(it?.error ?? 'not judged'); continue; }
        if (pick.label === 'next' && r.c + 1 < r.chunks.length) { r.c++; next.push(r); } else finish(r, pick.label, pick.p);
      }
      pending = next;
    }
  } catch (e) {
    error = String(e?.message || e);
    for (const r of pending) r.step.error = 'judge unavailable';
  } finally { await mt.flush(); }
  await writeJson(join(dataDir, 'scent.json'), out);
  return {
    tasks: Object.values(out).filter((s) => s.steps?.length).length, steps: records.length, rounds,
    judged: records.filter((r) => r.step.chunk != null).length, ms: Date.now() - t0,
    ...(error ? { judge_error: error } : {}),
  };
}

/** The example bank beside this file: `{attribution, examples: [{id, screen_type, rule, sev, text, box, why_good, source}]}`. */
export const readExamples = async () => JSON.parse(await readFile(new URL('./examples/critiques.json', import.meta.url), 'utf8'));

/**
 * `n` examples for one screen type: same-type examples first, then the rest; within each group the pick prefers a
 * rule not yet shown, then a source (uicrit / app-explore) not yet shown, then bank order. `type` null: no type match.
 */
export function pickExamples(bank, type, n = 4) {
  const left = [...bank], out = [];
  const src = (e) => String(e.source).split(':')[0];
  while (out.length < n && left.length) {
    const rules = new Set(out.map((e) => e.rule)), srcs = new Set(out.map(src));
    const score = (e) => (type && e.screen_type === type ? 4 : 0) + (rules.has(e.rule) ? 0 : 2) + (srcs.has(src(e)) ? 0 : 1);
    let best = 0;
    for (let i = 1; i < left.length; i++) if (score(left[i]) > score(left[best])) best = i;
    out.push(left.splice(best, 1)[0]);
  }
  return out;
}

/**
 * The step 8 prompt for one `app-explore-critic` call. `examples` off: exactly the 0.1.0 brief (dataDir, states,
 * batch). On: plus `examples` (the picked bank entries) and `example_ids` = per state the four ids matched to its
 * screen type, the judge's `screen_type` answer under the choice gate (unsure: no type, rule mix only).
 */
export async function criticBrief({ dataDir, states, batch }) {
  const lines = [`dataDir: ${dataDir}`, `states: ${JSON.stringify(states)}`, `batch: ${batch}`];
  if (!(await features(dataDir)).examples) return lines.join('\n');
  const [rubric, perceived, bank] = await Promise.all([
    readRubric(), readJson(join(dataDir, 'perceive.json')).catch(() => ({})), readExamples(),
  ]);
  const typeOf = (sid) => {
    const a = perceived[sid]?.answers?.screen_type;
    const p = a ? (a.probabilities?.[a.choice] ?? a.confidence ?? 0) : 0;
    return a && p >= rubric.gate.choice ? a.choice : null;
  };
  const ids = {}, used = new Map();
  for (const sid of states) {
    const pick = pickExamples(bank.examples, typeOf(sid));
    ids[sid] = pick.map((e) => e.id);
    for (const e of pick) used.set(e.id, e);
  }
  return [...lines, `examples: ${JSON.stringify([...used.values()])}`, `example_ids: ${JSON.stringify(ids)}`].join('\n');
}
