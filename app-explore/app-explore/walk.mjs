// Parent-kernel fallback walk for app-explore, used when `browser` is unavailable inside an app-explore-walker agent.
// Writes the same <data>/walks/<task>.json as the agent (plus `by: "kernel"`), driven by one completion per step
// over the mark list and visible text (roles: rubric.json models `walk_step`, `walk_survey`; counted in run.json
// `models`). Same limits: 15 steps, deny-list, write guard, acting stamp before each click. With run.json feature `seq`
// each step gets `seq` (SEQ 1-7, rated on the next screen; the last step in the survey) and the survey `sus` (10 items).
// With a persona `variant` (feature `personas` > 1) the walk plays that variant and writes walks/<task>-<variant>.json;
// `walkAll` runs every variant walk of the run with bounded concurrency.
//   const wk = await import(`${helpers}/walk.mjs`);
//   await wk.walkInKernel({ ax, browser, completion, persona, task, url, mode, dataDir });
//   await wk.walkAll({ ax, browser, completion, url, mode, dataDir });   // the n-1 kernel walks per task
import { existsSync } from 'node:fs';
import { mkdir, readFile, writeFile } from 'node:fs/promises';
import { features, meter, readRubric } from './config.mjs';

/** Walk file of a task, or of one persona variant walking it. */
export const walkFile = (dataDir, task, variant = null) => `${dataDir}/walks/${task.id}${variant ? `-${variant.id}` : ''}.json`;

export async function walkInKernel({ ax, browser, completion, persona, variant = null, task, url, mode, dataDir }) {
  const rubric = await readRubric();
  const mt = meter(dataDir, rubric);
  const seqOn = !!(await features(dataDir)).seq;
  const name = `walk-${task.id}${variant ? `-${variant.id}` : ''}`;
  const who = variant
    ? `${persona.name} (${persona.goal}), as this person: ${variant.name}. ${variant.note} Digital literacy ${variant.literacy}; ` +
      `${variant.hurry ? 'in a hurry' : 'not in a hurry'}; prior domain knowledge ${variant.domain}. Act like this person would`
    : `${persona.name} (${persona.goal})`;
  const STEP = {
    type: 'object', additionalProperties: false,
    required: ['last_outcome', 'last_confused', 'think', 'expected', 'mark', 'done', 'success'],
    properties: {
      last_outcome: { type: 'string', description: 'what your LAST action did to the screen: as-expected | unexpected: <note> | no-change; "none" when there was no last action' },
      last_confused: { type: 'boolean', description: 'the previous action surprised you or you lost your way' },
      think: { type: 'string', description: '1-3 sentences in the persona voice: what you see, what you will use and why' },
      expected: { type: 'string', description: 'what you expect your next action to do' },
      mark: { type: ['integer', 'null'], description: 'the mark number to click next; null when done or giving up' },
      done: { type: 'boolean', description: 'true when the task is reached or you give up' },
      success: { type: 'boolean', description: 'with done: the task goal is on screen' },
    },
  };
  const SURVEY = {
    type: 'object', additionalProperties: false, required: ['ease', 'confidence', 'comment'],
    properties: { ease: { type: 'integer', minimum: 1, maximum: 5 }, confidence: { type: 'integer', minimum: 1, maximum: 5 }, comment: { type: 'string' } },
  };
  const Q = rubric.seq;
  const rate = (v, hi) => (Number.isInteger(v) && v >= 1 && v <= hi ? v : null);
  if (seqOn) {
    const lastSeq = (what) => ({ type: ['integer', 'null'], minimum: 1, maximum: 7, description: `${what}: ${Q.question}` });
    STEP.required.push('last_seq');
    STEP.properties.last_seq = lastSeq('your LAST action, null when there was none');
    SURVEY.required.push('last_seq', 'sus');
    SURVEY.properties.last_seq = lastSeq('your final step');
    SURVEY.properties.sus = { type: 'array', minItems: 10, maxItems: 10, items: { type: 'integer', minimum: 1, maximum: 5 },
      description: `your answers to the 10 statements in order, ${Q.sus_scale}` };
  }
  const rule = mode === 'readonly'
    ? 'Never save, send, delete or submit. A create or edit task is done when its form is open with its submit control visible.'
    : 'Never log out.';
  const steps = [];
  let seq = 0, success = false;
  try {
    // openGuarded: guard first, then the run's login, then the app: every app request runs under the guard.
    const { tab } = await ax.openGuarded(browser, { url, dataDir, mode, name });
    for (let i = 0; i < 15; i++) {
      const m = (await ax.marks(tab)).filter((x) => !ax.denied(x.label, mode, x.href));
      const here = await tab.url();
      const text = String(await tab.text()).replace(/\s+/g, ' ').slice(0, 3000);
      const past = steps.map((s, k) => `${k + 1}. ${s.think} -> clicked ${s.mark} "${s.label}"`).join('\n') || '(none)';
      const last = steps[steps.length - 1];
      const lastLine = last ? `Your LAST action: clicked ${last.mark} "${last.label}", expecting: ${last.expected}. Compare with the screen below.`
        : 'This is your first look; there was no last action.';
      const r = await mt.complete(completion, 'walk_step',
        `You are ${who}. Your task: ${task.title}.\n${rule}\n` +
        `Use only what the screen shows.\nYour steps so far:\n${past}\n${lastLine}\n\nScreen ${here}\nVisible text: ${text}\n\n` +
        `Clickable elements (mark: role "label"):\n${m.map((x) => `${x.n}: ${x.role} "${x.label}"`).join('\n')}`,
        { schema: STEP });
      if (last) {
        const o = String(r.last_outcome || '');
        last.outcome = /^(as-expected|unexpected|no-change)/.test(o) ? o : 'no-change';
        last.confused = !!r.last_confused || o.startsWith('unexpected');
        if (seqOn) last.seq = rate(r.last_seq, 7);
      }
      const mk = m.find((x) => x.n === r.mark);
      if (r.done || !mk) {
        success = !!r.done && !!r.success;
        steps.push({ url: here, think: r.think, action: r.done ? 'done' : 'give-up', mark: null, label: null,
          expected: r.expected, outcome: r.done ? 'as-expected' : 'unexpected: picked no usable mark', confused: !r.done });
        break;
      }
      steps.push({ url: here, think: r.think, action: 'click', mark: mk.n, label: mk.label, expected: r.expected,
        outcome: 'no-change', confused: false });
      await ax.act(tab);
      try { await tab.click(`[data-apx-mark="${mk.n}"]`); } catch { steps[steps.length - 1].outcome = 'blocked: element not clickable'; }
      await ax.quiet(tab);
      seq = await ax.auditLeaks(tab, dataDir, seq, { task: task.id });
    }
    const s = await mt.complete(completion, 'walk_survey',
      `You are ${variant ? `${persona.name} (${variant.name})` : persona.name}. You just tried to: ${task.title}. Outcome: ${success ? 'reached' : 'not reached'}.\n` +
      `Your steps:\n${steps.map((x) => `- ${x.think} (${x.outcome})`).join('\n')}\n` +
      'Rate ease 1-5 (1 very hard), confidence 1-5 that the task is really done, and give one sentence of comment.' +
      (seqOn ? `\nRate your final step (last_seq). Then answer each statement about this app (${Q.sus_scale}):\n` +
        Q.sus_items.map((x, k) => `${k + 1}. ${x}`).join('\n') : ''),
      { schema: SURVEY });
    if (seqOn) {
      if (steps.length) steps[steps.length - 1].seq = rate(s.last_seq, 7);
      delete s.last_seq;
      if (!(Array.isArray(s.sus) && s.sus.length === 10 && s.sus.every((x) => rate(x, 5)))) delete s.sus;
    }
    const clicks = steps.filter((x) => x.action === 'click').length;
    const walk = { task: task.id, persona: persona.name, ...(variant ? { variant: variant.id } : {}), success, clicks, steps,
      first_mark: steps.find((x) => x.mark != null)?.mark ?? null, survey: s, by: 'kernel' };
    await mkdir(`${dataDir}/walks`, { recursive: true });
    await writeFile(walkFile(dataDir, task, variant), JSON.stringify(walk, null, 2));
    return walk;
  } finally {
    await mt.flush();
    try { await browser.close({ name }); } catch {}
  }
}

/**
 * Feature `personas` n > 1: the n-1 kernel walks of every task (or of `tasks`, ids), one per variant of the task's
 * persona (model.json `personas[].variants`, written by synthesize), at most `concurrency` at a time (default
 * rubric.json `personas.walk_concurrency`: `local` for a localhost / 127.0.0.1 app, else `remote`). A walk whose file
 * exists is skipped, so a re-run only redoes the missing ones; one failed walk does not stop the others.
 * Returns `{walked, skipped, errors: [{task, variant, error}]}`; with n = 1 nothing runs.
 */
export async function walkAll({ ax, browser, completion, url, mode, dataDir, tasks = null, concurrency = null }) {
  const n = (await features(dataDir)).personas ?? 1;
  const out = { walked: 0, skipped: 0, errors: [] };
  if (n <= 1) return out;
  const rubric = await readRubric();
  const model = JSON.parse(await readFile(`${dataDir}/model.json`, 'utf8'));
  const personas = Object.fromEntries(model.personas.map((p) => [p.id, p]));
  const jobs = [];
  for (const task of model.tasks) {
    if (tasks && !tasks.includes(task.id)) continue;
    const persona = personas[task.persona] || model.personas[0];
    for (const variant of (persona.variants || []).slice(0, n - 1)) {
      if (existsSync(walkFile(dataDir, task, variant))) out.skipped++;
      else jobs.push({ task, persona, variant });
    }
  }
  const local = /^(localhost|127\.0\.0\.1)$/.test(new URL(url).hostname);
  const width = concurrency ?? rubric.personas.walk_concurrency[local ? 'local' : 'remote'];
  let next = 0;
  const worker = async () => {
    while (next < jobs.length) {
      const { task, persona, variant } = jobs[next++];
      try {
        await walkInKernel({ ax, browser, completion, persona, variant, task, url, mode, dataDir });
        out.walked++;
      } catch (e) {
        out.errors.push({ task: task.id, variant: variant.id, error: String(e?.message ?? e) });
      }
    }
  };
  await Promise.all(Array.from({ length: Math.min(width, jobs.length) }, worker));
  return out;
}
