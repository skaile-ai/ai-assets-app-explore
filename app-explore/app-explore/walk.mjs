// Parent-kernel fallback walk for app-explore, used when `browser` is unavailable inside an app-explore-walker agent.
// Writes the same <data>/walks/<task>.json as the agent (plus `by: "kernel"`), driven by one completion per step
// over the mark list and visible text (roles: rubric.json models `walk_step`, `walk_survey`; counted in run.json
// `models`). Same limits: 15 steps, deny-list, write guard, acting stamp before each click.
//   const wk = await import(`${helpers}/walk.mjs`);
//   await wk.walkInKernel({ ax, browser, completion, persona, task, url, mode, dataDir });
import { mkdir, writeFile } from 'node:fs/promises';
import { meter, readRubric } from './config.mjs';

export async function walkInKernel({ ax, browser, completion, persona, task, url, mode, dataDir }) {
  const mt = meter(dataDir, await readRubric());
  const name = `walk-${task.id}`;
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
        `You are ${persona.name} (${persona.goal}). Your task: ${task.title}.\n${rule}\n` +
        `Use only what the screen shows.\nYour steps so far:\n${past}\n${lastLine}\n\nScreen ${here}\nVisible text: ${text}\n\n` +
        `Clickable elements (mark: role "label"):\n${m.map((x) => `${x.n}: ${x.role} "${x.label}"`).join('\n')}`,
        { schema: STEP });
      if (last) {
        const o = String(r.last_outcome || '');
        last.outcome = /^(as-expected|unexpected|no-change)/.test(o) ? o : 'no-change';
        last.confused = !!r.last_confused || o.startsWith('unexpected');
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
      `You are ${persona.name}. You just tried to: ${task.title}. Outcome: ${success ? 'reached' : 'not reached'}.\n` +
      `Your steps:\n${steps.map((x) => `- ${x.think} (${x.outcome})`).join('\n')}\n` +
      'Rate ease 1-5 (1 very hard), confidence 1-5 that the task is really done, and give one sentence of comment.',
      { schema: SURVEY });
    const clicks = steps.filter((x) => x.action === 'click').length;
    const walk = { task: task.id, persona: persona.name, success, clicks, steps,
      first_mark: steps.find((x) => x.mark != null)?.mark ?? null, survey: s, by: 'kernel' };
    await mkdir(`${dataDir}/walks`, { recursive: true });
    await writeFile(`${dataDir}/walks/${task.id}.json`, JSON.stringify(walk, null, 2));
    return walk;
  } finally {
    await browser.close({ name });
    await mt.flush();
  }
}
