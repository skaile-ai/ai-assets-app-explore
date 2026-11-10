// Feature `mental_model` for app-explore: a simulated first-time user's model of the app, grown along crawl edges
// and walks. Re-exported by pipeline.mjs as `mentalModel`; called from SKILL.md steps 6 and 8:
//   await ap.mentalModel({ judgeBatch, completion }, { dataDir });                  // crawl replay
//   await ap.mentalModel({ judgeBatch, completion }, { dataDir, pass: 'walks' });   // after the walks
// Call kinds (rubric.json `models`): mental_predict (smol), mental_match (judge), mental_update (smol).
import { readdir, readFile, writeFile } from 'node:fs/promises';
import { join } from 'node:path';
import { features, meter } from './config.mjs';
import { ask, load, norm, sameWord } from './pipeline.mjs';

const readJson = async (p) => JSON.parse(await readFile(p, 'utf8'));
const writeJson = (p, v) => writeFile(p, JSON.stringify(v, null, 2));

const PREDICT_SCHEMA = {
  type: 'object', additionalProperties: false, required: ['kind', 'heading', 'object', 'purpose'],
  properties: {
    kind: { type: 'string', enum: ['page', 'dialog', 'menu', 'tab', 'nothing'] },
    heading: { type: 'string' }, object: { type: 'string' }, purpose: { type: 'string' },
  },
};

/** Schema of one model update; `walk` adds the step index to concepts, surprises and contradictions. */
function updateSchema(walk) {
  const step = walk ? { step: { type: 'integer' } } : {};
  const req = walk ? ['step'] : [];
  const surprise = { type: 'string', enum: ['expectation', 'affordance', 'location'] };
  return {
    type: 'object', additionalProperties: false,
    required: ['concepts', walk ? 'surprises' : 'surprise', 'contradictions'],
    properties: {
      concepts: { type: 'array', items: { type: 'object', additionalProperties: false,
        required: ['name', 'kind', 'believed_attributes', 'confidence', 'op', ...req],
        properties: {
          name: { type: 'string' },
          kind: { type: 'string', enum: ['object', 'place', 'action'] },
          believed_attributes: { type: 'array', items: { type: 'string' } },
          confidence: { type: 'number' },
          op: { type: 'string', enum: ['add', 'confirm', 'contradict'] }, ...step,
        } } },
      ...(walk
        ? { surprises: { type: 'array', items: { type: 'object', additionalProperties: false, required: ['step', 'kind'],
          properties: { step: { type: 'integer' }, kind: surprise } } } }
        : { surprise }),
      contradictions: { type: 'array', items: { type: 'object', additionalProperties: false,
        required: ['kind', 'expected', 'observed', 'names', 'naming', ...req],
        properties: {
          kind: { type: 'string', enum: ['naming', 'location', 'affordance'] },
          expected: { type: 'string' }, observed: { type: 'string' },
          names: { type: 'array', items: { type: 'string' } },
          naming: { type: 'string', enum: ['same-object-different-name', 'same-label-different-target', 'none'] }, ...step,
        } } },
    },
  };
}

const UPDATE_RULES = `Concepts are what the user believes exists: objects (things like projects or invoices), places (screens or areas like Settings) and actions (things they can do), each with believed attributes and a confidence 0-1 that it exists as believed. Use the words the screens use.

Return:
- concepts: at most 8 per step that it adds, confirms or contradicts (op add / confirm / contradict). confidence: how sure the user now is.
- surprise (for a prediction that did not match): expectation (the screen shows another thing than the label promised), affordance (the control looked like one kind of control, e.g. a link to a page, and acted like another, e.g. opened a menu or only expanded a tree), location (the expected thing exists but lives elsewhere than assumed).
- contradictions: only with direct evidence in this step that clashes with something the model already held; most steps have none. Something new that the model simply did not know yet is no contradiction, and the prediction miss itself is already logged: never repeat it here. naming: names = the two names; naming = same-object-different-name (a known concept appears here under another name) or same-label-different-target (a known name now means a different thing). location: something known turns up where the user did not expect it. affordance: a control looks like one thing and does another. expected / observed: one short sentence each. naming = none for location and affordance.`;

/** The concept list of a mental model: prompt lines and applying one update's concept ops. */
function conceptStore(concepts, screenName) {
  const lines = (max) => {
    const top = [...concepts].sort((a, b) => (b.confirmations - a.confirmations) || (b.confidence - a.confidence)).slice(0, max);
    return top.length ? top.map((c) => `- ${c.name} (${c.kind}${c.believed_attributes.length ? `: ${c.believed_attributes.slice(0, 6).join(', ')}` : ''})`
      + ` seen on ${c.seen_in.slice(0, 3).map((s) => `"${screenName[s] ?? s}"`).join(', ')}`).join('\n') : '(nothing yet)';
  };
  /**
   * Apply concept ops, each at `stateOf(op)`; returns counts. A known name counts as confirm unless contradicted.
   * A new concept records `found_via` = `viaOf(op)`, the label of the click that first showed it (null: the entry).
   */
  const apply = (ops, stateOf, step, viaOf = () => null) => {
    const n = { added: 0, confirmed: 0, contradicted: 0 };
    for (const o of ops ?? []) {
      const name = String(o.name ?? '').trim();
      if (!name) continue;
      const sid = stateOf(o);
      let c = concepts.find((x) => sameWord(x.name, name));
      if (!c) {
        c = { id: `c${concepts.length + 1}`, name, kind: o.kind, believed_attributes: [], seen_in: [],
          first_seen: { step, state: sid }, found_via: viaOf(o) ?? null, confidence: 0, confirmations: 0, contradictions: 0 };
        concepts.push(c);
        n.added++;
      } else if (o.op === 'contradict') { c.contradictions++; n.contradicted++; } else { c.confirmations++; n.confirmed++; }
      for (const a of o.believed_attributes ?? []) if (a && !c.believed_attributes.some((b) => norm(b) === norm(a))) c.believed_attributes.push(a);
      if (sid && !c.seen_in.includes(sid)) c.seen_in.push(sid);
      c.confidence = Math.round(Math.min(1, Math.max(0, Number(o.confidence) || 0)) * 100) / 100;
    }
    return { ...n, concepts: concepts.length };
  };
  return { concepts, lines, apply };
}

/** What a state shows, from the crawl and its perceive extract. */
function observedOf(s, perceived) {
  const x = perceived[s.id]?.extract;
  return {
    kind: s.kind, heading: s.heading || s.title || '',
    purpose: x?.purpose ?? '',
    objects: (x?.objects ?? []).slice(0, 8).map((o) => `${o.name} (${o.as})`),
    actions: (x?.actions ?? []).slice(0, 8).map((a) => `${a.verb} ${a.object}`),
  };
}
const observedLine = (o) => `${o.kind} "${o.heading}": ${o.purpose}${o.objects.length ? ` Shows: ${o.objects.join(', ')}.` : ''}`;
const predictedLine = (p) => (p ? `${p.kind} "${p.heading}" about ${p.object}: ${p.purpose}` : '');

/** Gated bool (rubric.json `gate`): true / false inside the gate, null between. */
const gatedBool = (p, gate) => (typeof p !== 'number' ? null : p >= gate.bool_true ? true : p <= gate.bool_false ? false : null);

const SURPRISES = new Set(['expectation', 'affordance', 'location']);
const CONTRADICTIONS = new Set(['naming', 'location', 'affordance']);
const surpriseKind = (k) => (SURPRISES.has(k) ? k : 'expectation');

/**
 * Contradictions of one update as violations: unknown kinds dropped, a naming pair once per run, and a location or
 * affordance contradiction at a step whose prediction already missed is that miss again (its `surprise` classified it).
 */
function pushContradictions(violations, list, at, missed) {
  for (const c of list ?? []) {
    if (!CONTRADICTIONS.has(c.kind)) continue;
    const names = (c.names ?? []).filter(Boolean).slice(0, 2);
    if (c.kind === 'naming') {
      if (names.length < 2 || sameWord(names[0], names[1])) continue;
      const key = names.map(norm).sort().join('|');
      if (violations.some((v) => v.kind === 'naming' && v.names.map(norm).sort().join('|') === key)) continue;
    } else if (missed(c)) continue;
    violations.push({ kind: c.kind, ...at(c), expected: c.expected, observed: c.observed,
      ...(c.kind === 'naming' ? { names, naming: c.naming === 'none' ? 'same-object-different-name' : c.naming } : {}) });
  }
}

const renumber = (violations) => violations.forEach((v, i) => { v.id = `v${i + 1}`; });

/**
 * A simulated first-time user's model of the app, grown only from what it has seen.
 * `pass: 'crawl'` (step 6): seeds the model from the entry state, then replays graph edges in BFS order (capped at
 * rubric.json `mental.max_edges`, or `maxEdges`): per edge `smol` predicts what clicking the label shows
 * (`mental_predict`), the judge decides `matches` on the target's screenshot and perceive extract (`mental_match`,
 * gated), `smol` updates the concepts and logs contradictions (`mental_update`). `pass: 'walks'` (after step 8):
 * restarts from the crawl's model and feeds each base walk (walks/*.json without `variant`) in turn (`expected`/`outcome` per step; the judge
 * decides free-text outcomes, `blocked` steps count for nothing), one `smol` update per walk, at most
 * `mental.max_walk_steps` steps in all. Writes <data>/mentalmodel.json `{cap, concepts, timeline, violations,
 * after_crawl, walks?, errors?}`; violation kinds expectation | affordance | location | naming.
 * Feature off: writes nothing and returns `{skipped}`.
 */
export async function mentalModel({ judgeBatch, completion }, { dataDir, pass = 'crawl', maxEdges = undefined }) {
  if (!(await features(dataDir)).mental_model) return { skipped: 'mental_model off' };
  if (pass !== 'crawl' && pass !== 'walks') throw new Error(`mentalModel: pass must be crawl or walks, got ${pass}`);
  return pass === 'crawl' ? mentalCrawl({ judgeBatch, completion }, { dataDir, maxEdges })
    : mentalWalks({ judgeBatch, completion }, { dataDir });
}

async function mentalCrawl({ judgeBatch, completion }, { dataDir, maxEdges }) {
  const t0 = Date.now();
  const { graph, rubric, reports, screens } = await load(dataDir, { screens: true });
  const perceived = await readJson(join(dataDir, 'perceive.json'));
  const cfg = rubric.mental;
  const byId = Object.fromEntries(graph.states.map((s) => [s.id, s]));
  const screenName = Object.fromEntries(graph.states.map((s) => [s.id, s.heading || s.title || s.id]));
  // BFS order of states from the entry, unreachable ones after; edges by their source's rank, then crawl order
  const order = [graph.states[0].id];
  for (let i = 0; i < order.length; i++) {
    for (const e of graph.edges) if (e.from === order[i] && byId[e.to] && !order.includes(e.to)) order.push(e.to);
  }
  for (const s of graph.states) if (!order.includes(s.id)) order.push(s.id);
  const rank = Object.fromEntries(order.map((id, i) => [id, i]));
  const all = graph.edges.map((e, i) => ({ ...e, i })).filter((e) => e.from !== e.to && byId[e.from] && byId[e.to])
    .sort((a, b) => rank[a.from] - rank[b.from] || a.i - b.i);
  const cap = maxEdges ?? cfg.max_edges;
  const edges = all.slice(0, cap);
  const labelOf = (e) => e.label ?? (screens[e.from]?.marks ?? []).find((m) => m.n === e.mark)?.label ?? null;
  const store = conceptStore([], screenName);
  const timeline = [], violations = [], errors = [];
  const mt = meter(dataDir, rubric);
  const seen = new Set();
  let judgeDead = null;
  try {
    // step 0: the entry screen, seen without a prediction
    const entry = graph.states[0];
    const ob0 = observedOf(entry, perceived);
    const u0 = await ask(mt, completion, 'mental_update',
      `You keep the mental model of a first-time user of a web app. They just opened it and see this first screen:\n${observedLine(ob0)}\nActions offered: ${ob0.actions.join('; ')}\n\n${UPDATE_RULES}\n\nNo prediction was made: surprise = expectation, contradictions empty.`,
      { schema: updateSchema(false) });
    if (u0.error) errors.push({ step: 0, kind: 'mental_update', error: u0.error });
    seen.add(entry.id);
    timeline.push({ step: 0, source: 'crawl', state: entry.id, from: null, label: null, predicted: null, matches: null, p: null,
      ...store.apply(u0.value?.concepts, () => entry.id, 0), violations: [] });

    for (const [k, e] of edges.entries()) {
      const step = k + 1;
      const from = byId[e.from], to = byId[e.to];
      const mark = (screens[e.from]?.marks ?? []).find((m) => m.n === e.mark);
      const control = `${mark?.role ?? 'control'} "${e.label ?? mark?.label ?? ''}"`;
      const pr = await ask(mt, completion, 'mental_predict',
        `You are a first-time user of a web app. You know only what you have seen so far:\n${store.lines(cfg.prompt_concepts)}\n`
        + `Screens seen: ${[...seen].map((s) => `"${screenName[s]}"`).join(', ')}.\n\n`
        + `You are on "${screenName[e.from]}" (${from.kind}), see ${control} there and are about to click it. Predict briefly what will appear: `
        + 'kind (page, dialog, menu, tab, nothing), its heading, the main object it shows, its purpose in one short sentence. '
        + 'Go by the label and what you know, the way a person guesses from a label; always commit to a concrete guess, never answer unknown.',
        { schema: PREDICT_SCHEMA });
      const predicted = pr.value ?? null;
      if (pr.error) errors.push({ step, kind: 'mental_predict', error: pr.error });
      const ob = observedOf(to, perceived);
      let p = null;
      if (predicted && !judgeDead) {
        const key = `e${step}`;
        try {
          const items = await mt.judge(judgeBatch, 'mental_match',
            { [key]: { from: screenName[e.from], clicked: control, predicted, observed: ob } },
            { matches: cfg.match }, { images: { [key]: [join(reports, to.shot)] }, intent: `app-explore mental model, edge ${step}` });
          if (items[key]?.ok) p = items[key].answers.matches.bool;
          else errors.push({ step, kind: 'mental_match', error: String(items[key]?.error ?? 'not judged') });
        } catch (err) { judgeDead = String(err?.message || err); errors.push({ step, kind: 'mental_match', error: judgeDead }); }
      }
      const matches = gatedBool(p, rubric.gate);
      const verdict = matches === true ? 'matched' : matches === false ? 'did NOT match' : 'is unclear';
      const up = await ask(mt, completion, 'mental_update',
        `You keep the mental model of a first-time user of a web app.\nCurrent model:\n${store.lines(cfg.prompt_concepts)}\n\n`
        + `Step: on "${screenName[e.from]}" they clicked ${control}${predicted ? `, expecting: ${predictedLine(predicted)}` : ''}.\n`
        + `What appeared: ${observedLine(ob)}\nActions offered there: ${ob.actions.join('; ')}\nThe prediction ${verdict}.\n\n${UPDATE_RULES}`,
        { schema: updateSchema(false) });
      if (up.error) errors.push({ step, kind: 'mental_update', error: up.error });
      seen.add(e.to);
      const before = violations.length;
      const at = () => ({ source: 'crawl', step, state: e.to, from: e.from, label: e.label ?? null, mark: e.mark ?? null });
      if (matches === false) {
        violations.push({ kind: surpriseKind(up.value?.surprise), ...at(), expected: predictedLine(predicted),
          observed: observedLine(ob), p: Math.round((1 - p) * 100) / 100 });
      }
      pushContradictions(violations, up.value?.contradictions, at, () => matches === false);
      renumber(violations);
      timeline.push({ step, source: 'crawl', state: e.to, from: e.from, label: e.label ?? null, predicted, matches,
        p: p == null ? null : Math.round(p * 100) / 100, ...store.apply(up.value?.concepts, () => e.to, step, () => labelOf(e)),
        violations: violations.slice(before).map((v) => v.id) });
    }
  } finally { await mt.flush(); }
  const out = {
    cap: { edges: cap, total_edges: all.length, replayed: edges.length, truncated: all.length > edges.length },
    concepts: store.concepts, timeline, violations,
    after_crawl: { concepts: structuredClone(store.concepts), steps: timeline.length },
    ...(errors.length ? { errors } : {}),
  };
  await writeJson(join(dataDir, 'mentalmodel.json'), out);
  return {
    edges: edges.length, of: all.length, concepts: store.concepts.length, violations: violations.length,
    unsure: timeline.filter((t) => t.step && t.matches === null).length, errors: errors.length, ms: Date.now() - t0,
    ...(judgeDead ? { judge_error: judgeDead } : {}),
  };
}

/** Outcome of a walk step: true / false from the walker's prefix, 'blocked' (the guard; says nothing), null = free text. */
function outcomeMatch(outcome) {
  const o = String(outcome ?? '').trim().toLowerCase();
  if (/^as-expected/.test(o)) return true;
  if (/^(unexpected|no-change)/.test(o)) return false;
  if (/^blocked/.test(o)) return 'blocked';
  return null;
}

async function mentalWalks({ judgeBatch, completion }, { dataDir }) {
  const t0 = Date.now();
  const { graph, rubric } = await load(dataDir);
  const cfg = rubric.mental;
  let mm;
  try { mm = await readJson(join(dataDir, 'mentalmodel.json')); } catch {
    throw new Error('mentalModel walks: no mentalmodel.json; run the crawl pass (step 6) first');
  }
  const perceived = await readJson(join(dataDir, 'perceive.json'));
  const byId = Object.fromEntries(graph.states.map((s) => [s.id, s]));
  const screenName = Object.fromEntries(graph.states.map((s) => [s.id, s.heading || s.title || s.id]));
  const strip = (u) => String(u ?? '').replace(/#.*$/, '');
  const pathOf = (u) => { try { return new URL(u).pathname; } catch { return null; } };
  const pages = graph.states.filter((s) => s.kind === 'page');
  const urlState = (u) => (u ? (pages.find((s) => strip(s.url) === strip(u)) ?? graph.states.find((s) => strip(s.url) === strip(u))
    ?? pages.find((s) => pathOf(s.url) === pathOf(u)))?.id ?? null : null);
  // the state a step led to: the crawl edge with its label from the step's screen, else the next step's page when the
  // step navigated (null when that page is off the crawled graph), else the step's own screen
  const resultState = (st, next) => {
    const from = urlState(st.url);
    const e = from && st.label ? graph.edges.find((x) => x.from === from && x.label && norm(x.label) === norm(st.label)) : null;
    const moved = next?.url && strip(next.url) !== strip(st.url);
    return { from, to: e?.to ?? (moved ? urlState(next.url) : from) };
  };
  const store = conceptStore(structuredClone(mm.after_crawl.concepts), screenName);
  const timeline = mm.timeline.filter((t) => t.source === 'crawl');
  const violations = mm.violations.filter((v) => v.source === 'crawl');
  let files = [];
  try { files = (await readdir(join(dataDir, 'walks'))).filter((n) => n.endsWith('.json')).sort(); } catch {}
  const walks = [];
  let budget = cfg.max_walk_steps, truncated = false;
  for (const f of files) {
    const w = await readJson(join(dataDir, 'walks', f));
    if (w.variant) continue; // persona variants (walks/<task>-<variant>.json): the model stays one person's
    const raw = w.steps ?? [];
    const steps = [];
    raw.forEach((st, i) => {
      if (['done', 'give-up'].includes(st.action) || !st.expected) return;
      if (budget <= 0) { truncated = true; return; }
      budget--;
      // url: where the step led (the next step's page), for violations off the crawled graph
      steps.push({ i, st, ...resultState(st, raw[i + 1]), url: raw[i + 1]?.url ?? st.url, match: outcomeMatch(st.outcome), p: null });
    });
    if (steps.length) walks.push({ id: f.replace(/\.json$/, ''), task: w.task ?? null, steps });
  }
  const mt = meter(dataDir, rubric);
  const errors = [];
  let judgeError = null;
  try {
    const free = walks.flatMap((w) => w.steps.filter((s) => s.match === null).map((s) => [`${w.id}#${s.i}`, s, w.id]));
    if (free.length) {
      try {
        const states = Object.fromEntries(free.map(([k, s]) => [k, { step: `${s.st.action} "${s.st.label ?? ''}"`, expected: s.st.expected, outcome: s.st.outcome }]));
        const items = await mt.judge(judgeBatch, 'mental_match', states, { matches: cfg.walk_match }, { intent: 'app-explore mental model, walk outcomes' });
        for (const [k, s, walk] of free) {
          if (items[k]?.ok) { s.p = items[k].answers.matches.bool; s.match = gatedBool(s.p, rubric.gate); }
          else errors.push({ walk, step: s.i, kind: 'mental_match', error: String(items[k]?.error ?? 'not judged') });
        }
      } catch (err) {
        judgeError = String(err?.message || err);
        errors.push({ walk: '*', kind: 'mental_match', error: judgeError, steps: free.length });
      }
    }
    for (const w of walks) {
      const stepNo = timeline.length;
      const lines = w.steps.map((s) => {
        const verdict = s.match === true ? 'as expected' : s.match === false ? 'NOT as expected'
          : s.match === 'blocked' ? 'blocked by the test run, ignore' : 'unclear';
        return `${s.i}. on "${screenName[s.from] ?? s.st.url}" ${s.st.action} "${s.st.label ?? ''}", expecting: ${s.st.expected}. Outcome: ${s.st.outcome} [${verdict}]`
          + (s.to && s.to !== s.from && perceived[s.to] ? ` Led to: ${observedLine(observedOf(byId[s.to], perceived))}` : '');
      }).join('\n');
      const up = await ask(mt, completion, 'mental_update',
        `You keep the mental model of a first-time user of a web app.\nCurrent model:\n${store.lines(cfg.prompt_concepts)}\n\n`
        + `The user now worked through these steps of one task (step number first):\n${lines}\n\n${UPDATE_RULES}\n`
        + 'Here every concept, surprise and contradiction names its step number; give surprises only for steps marked NOT as expected.',
        { schema: updateSchema(true) });
      if (up.error) errors.push({ walk: w.id, kind: 'mental_update', error: up.error });
      const byStep = Object.fromEntries(w.steps.map((s) => [s.i, s]));
      const last = w.steps[w.steps.length - 1];
      const before = violations.length;
      const at = (c) => {
        const s = byStep[c.step] ?? last;
        return { source: 'walk', walk: w.id, task: w.task, step: stepNo, walk_step: s.i, state: s.to, from: s.from,
          label: s.st.label ?? null, mark: s.st.mark ?? null, url: s.url };
      };
      const kindOf = Object.fromEntries((up.value?.surprises ?? []).map((x) => [x.step, x.kind]));
      for (const s of w.steps.filter((x) => x.match === false)) {
        violations.push({ kind: surpriseKind(kindOf[s.i]), ...at({ step: s.i }), expected: s.st.expected,
          observed: String(s.st.outcome).replace(/^(unexpected|no-change)\s*:?\s*/i, '') || s.st.outcome,
          p: s.p == null ? null : Math.round((1 - s.p) * 100) / 100 });
      }
      pushContradictions(violations, up.value?.contradictions, at, (c) => (byStep[c.step] ?? last).match === false);
      renumber(violations);
      timeline.push({ step: stepNo, source: 'walk', walk: w.id, task: w.task, state: last.to, from: null, label: null,
        steps: w.steps.length, matched: w.steps.filter((s) => s.match === true).length,
        mismatched: w.steps.filter((s) => s.match === false).length,
        ...store.apply(up.value?.concepts, (o) => byStep[o.step]?.to ?? last.to, stepNo, (o) => byStep[o.step]?.st.label ?? null),
        violations: violations.slice(before).map((v) => v.id) });
    }
  } finally { await mt.flush(); }
  const out = { ...mm, concepts: store.concepts, timeline, violations,
    walks: { fed: walks.length, steps: walks.reduce((n, w) => n + w.steps.length, 0), cap: cfg.max_walk_steps, truncated } };
  const errs = [...(mm.errors ?? []).filter((x) => !x.walk), ...errors];
  if (errs.length) out.errors = errs; else delete out.errors;
  await writeJson(join(dataDir, 'mentalmodel.json'), out);
  return {
    walks: walks.length, steps: out.walks.steps, concepts: store.concepts.length, violations: violations.length,
    walk_violations: violations.filter((v) => v.source === 'walk').length, errors: errors.length, ms: Date.now() - t0,
    ...(judgeError ? { judge_error: judgeError } : {}),
  };
}
