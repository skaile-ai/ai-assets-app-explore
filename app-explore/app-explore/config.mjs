// Feature switches and model roles for app-explore, shared by pipeline.mjs and walk.mjs and called from SKILL.md step 1.
//   const cfg = await import(`${helpers}/config.mjs`);
//   const features = cfg.resolveFeatures(await cfg.readRubric(), { with: 'saliency', without: ['seq'], personas: 2 });
//   const f = await cfg.features(dataDir);                  // later steps: the run's switches, from run.json only
// Model calls go through `meter`: the role comes from rubric.json `models`, the count lands in run.json `models`.
// Agents (walker, critic) run on the model of their own definition; `recordAgent` reads it from there.
import { readFile } from 'node:fs/promises';
import { homedir } from 'node:os';
import { join } from 'node:path';
import { fileURLToPath } from 'node:url';
import { writeRun } from './crawl.mjs';

const RUBRIC = fileURLToPath(new URL('./rubric.json', import.meta.url));

export const readRubric = async () => JSON.parse(await readFile(RUBRIC, 'utf8'));

const names = (v) => (Array.isArray(v) ? v : String(v ?? '').split(','))
  .map((s) => String(s).trim()).filter(Boolean);

/**
 * Resolved switches from rubric.json `features` (defaults) and the run's arguments: `with`/`without` take feature
 * names (array or comma string) of the boolean features, `personas` a whole number ≥ 1. Throws on an unknown name,
 * on a name in both lists and on a bad `personas`; the message lists the valid names.
 */
export function resolveFeatures(rubric, { with: on = [], without: off = [], personas = undefined } = {}) {
  const defaults = rubric.features;
  const toggles = Object.keys(defaults).filter((k) => typeof defaults[k] === 'boolean');
  const valid = `valid: ${toggles.join(', ')} (and personas <n>)`;
  const w = names(on), wo = names(off);
  const unknown = [...w, ...wo].filter((f) => !toggles.includes(f));
  if (unknown.length) throw new Error(`app-explore: unknown feature ${unknown.join(', ')}; ${valid}`);
  const both = w.filter((f) => wo.includes(f));
  if (both.length) throw new Error(`app-explore: feature ${both.join(', ')} both in with and without`);
  const out = { ...defaults };
  for (const f of w) out[f] = true;
  for (const f of wo) out[f] = false;
  if (personas !== undefined && personas !== null) {
    const n = Number(personas);
    if (!Number.isInteger(n) || n < 1) throw new Error(`app-explore: personas must be a whole number >= 1, got ${personas}`);
    out.personas = n;
  }
  return out;
}

/** The run's switches: run.json `features` over rubric.json defaults (a run older than a feature gets its default). */
export async function features(dataDir) {
  let run = {};
  try { run = JSON.parse(await readFile(join(dataDir, 'run.json'), 'utf8')); } catch {}
  return { ...(await readRubric()).features, ...run.features };
}

/** Pull every settled item of a judge batch, then release it. Returns {items: {key: item}, status}. */
async function drainAll(batch) {
  const items = {};
  let status = {};
  try {
    for (;;) {
      const got = await batch.drain(120);
      for (const [k, item] of got) items[k] = item;
      if (!got.length && !(status = await batch.status()).running) break;
    }
  } finally { await batch.close(); }
  return { items, status };
}

const COMPLETION_ROLES = new Set(['smol', 'slow', 'default']);

/**
 * Model calls of one pipeline function, by call kind (a key of rubric.json `models`). `complete` runs one
 * `completion` with the kind's role as `model`; `judge` runs one `judgeBatch` (role must be `judge`) and drains it.
 * Both count calls and seconds per kind in memory; `flush()` adds them into run.json `models[<kind>]` =
 * `{role, calls, secs}` (plus `cost` when the judge reports one), summed across calls and cells.
 * secs: summed per-call wall time for completions, batch wall time for a judge batch.
 */
export function meter(dataDir, rubric) {
  const acc = {};
  const roleOf = (kind) => {
    const role = rubric.models?.[kind];
    if (!role) throw new Error(`app-explore: rubric.json models has no role for "${kind}"`);
    return role;
  };
  const add = (kind, role, calls, secs, cost) => {
    const a = (acc[kind] ||= { role, calls: 0, secs: 0 });
    a.calls += calls;
    a.secs += secs;
    if (typeof cost === 'number') a.cost = (a.cost ?? 0) + cost;
  };
  return {
    role: roleOf,
    /** One structured completion of call kind `kind`; returns the parsed value, throws like `completion`. */
    async complete(completion, kind, prompt, opts = {}) {
      const role = roleOf(kind);
      if (!COMPLETION_ROLES.has(role)) throw new Error(`app-explore: models.${kind} = "${role}" is no completion role (smol, slow, default)`);
      const t = Date.now();
      try { return await (await completion(prompt, { ...opts, model: role })).wait(); } finally { add(kind, role, 1, (Date.now() - t) / 1000); }
    },
    /** One judge batch of call kind `kind`, drained; returns {key: item}. Throws when the batch dies wholesale. */
    async judge(judgeBatch, kind, states, questions, opts = {}) {
      const role = roleOf(kind);
      if (role !== 'judge') throw new Error(`app-explore: models.${kind} = "${role}"; this call site needs role judge`);
      const t = Date.now();
      let calls = 0, cost;
      try {
        const b = await judgeBatch(states, questions, opts);
        calls = Object.keys(states).length;
        const { items, status } = await drainAll(b);
        cost = status.cost;
        return items;
      } finally { add(kind, role, calls, (Date.now() - t) / 1000, cost); }
    },
    /** Count calls made outside this kernel (agents) under call kind `kind` and model `role`; flushed like the others. */
    record(kind, calls, secs, role) { add(kind, role, calls, secs); },
    /** Add this meter's counts into run.json `models` and reset them. */
    async flush() {
      const done = Object.entries(acc);
      for (const k of Object.keys(acc)) delete acc[k];
      if (!done.length) return;
      await writeRun(dataDir, (run) => {
        const models = { ...run.models };
        for (const [kind, a] of done) {
          const m = models[kind] ?? { role: a.role, calls: 0, secs: 0 };
          models[kind] = {
            role: a.role, calls: m.calls + a.calls, secs: Math.round((m.secs + a.secs) * 100) / 100,
            ...(a.cost != null || m.cost != null ? { cost: Math.round(((m.cost ?? 0) + (a.cost ?? 0)) * 1e6) / 1e6 } : {}),
          };
        }
        return { models };
      });
    },
  };
}

/** The agent each agent call kind dispatches, by bare name (the eval kernel's `agent()` takes no model override). */
export const AGENTS = { walker_agent: 'app-explore-walker', critic: 'app-explore-critic' };

/**
 * The model role an omp agent runs on: the `model:` line of its definition's frontmatter (`@task_standard` →
 * `task_standard`), looked up where omp discovers agents (`<cwd>/.omp/agents`, then `~/.omp/agent/agents`).
 * null when no definition is found there.
 */
export async function agentRole(name) {
  for (const dir of [join(process.cwd(), '.omp', 'agents'), join(homedir(), '.omp', 'agent', 'agents')]) {
    let text;
    try { text = await readFile(join(dir, `${name}.md`), 'utf8'); } catch { continue; }
    const fm = text.match(/^---\n([\s\S]*?)\n---/)?.[1] ?? '';
    const m = fm.match(/^model:\s*["']?([^"'\n]+?)["']?\s*$/m);
    return m ? m[1].replace(/^@/, '') : null;
  }
  return null;
}

/**
 * Count agent runs into run.json `models[kind]` like `meter` counts kernel calls: `kind` is a key of `AGENTS`
 * (`walker_agent`, `critic`), `calls` the agents run, `secs` their wall time. The recorded `role` is the agent
 * definition's model (`agentRole`), not a rubric.json key. SKILL.md steps 5, 6 and 8 call it after each wave.
 */
export async function recordAgent(dataDir, kind, { calls = 1, secs = 0 } = {}) {
  const name = AGENTS[kind];
  if (!name) throw new Error(`app-explore: recordAgent kind "${kind}"; valid: ${Object.keys(AGENTS).join(', ')}`);
  const mt = meter(dataDir, await readRubric());
  mt.record(kind, calls, secs, await agentRole(name));
  await mt.flush();
}
