#!/usr/bin/env python3
"""Feature map of a merged app-model: coverage check, status and feature-map.md, skaileup proposals.

Usage ($PY = "uv run --quiet --with pyyaml==6.0.3 python3"):
  $PY featuremap.py check <dir>            coverage gaps of <dir>/app-model.merged.yaml; exit 1 while any exist
  $PY featuremap.py render <dir>           sets features[].status, writes <dir>/feature-map.md
  $PY featuremap.py propose <dir> <repo>   appends ## Ideas rows and proposed glossary terms to <repo>/_concept/

The roster (feature rows, ## Ideas rows, ## Cut lines) is read from <repo>/_concept/05_features/featuresets.md; the
repo is the merged model's `app.root` for check and render.
"""

import datetime
import re
import sys
from pathlib import Path

import model as am

STATUSES = ('built', 'hidden', 'unbuilt', 'undocumented', 'ui-only')
ROW = re.compile(r'^\|\s*`?([^|`]+?)`?\s*\|')
TERM = re.compile(r'^\*\*(.+?)\*\*\s*\(`([a-z0-9-]+)`\):')


def today():
    return datetime.date.today().isoformat()


def load_dir(d):
    d = Path(d)
    m = am.load(d / 'app-model.merged.yaml')
    errors = am.validate(m)
    if errors:
        sys.exit('\n'.join(['app-model.merged.yaml does not validate:', *errors]))
    present = [s for s in am.SOURCES if (d / f'app-model.{s}.yaml').is_file()]
    docs = am.load(d / 'app-model.docs.yaml') if 'docs' in present else None
    return d, m, present, docs


# ------------------------------------------------------------------ roster

def roster(repo):
    """{rows, ideas, cut, featuresets, path, lines} of <repo>/_concept/05_features/featuresets.md (empty when absent)."""
    out = {'rows': set(), 'ideas': set(), 'cut': set(), 'featuresets': set(), 'path': None, 'lines': []}
    if not repo:
        return out
    path = Path(repo) / '_concept/05_features/featuresets.md'
    out['path'] = path
    if not path.is_file():
        return out
    out['lines'] = path.read_text(encoding='utf-8').splitlines()
    section = None
    for line in out['lines']:
        s = line.strip()
        if s.startswith('## '):
            section = s[3:].strip()
            if am.slug(section) == section and section.lower() not in ('ideas', 'cut', 'roles'):
                out['featuresets'].add(section)
            continue
        if section is None:
            continue
        low = section.lower()
        if low == 'cut':
            out['cut'].update(re.findall(r'`([a-z0-9-]+)`', s))
            m = re.match(r'^[-*]\s*([a-z0-9-]+)', s)
            if m:
                out['cut'].add(m.group(1))
            continue
        m = ROW.match(s)
        if not m or set(m.group(1)) <= set('-: '):
            continue
        cell = m.group(1).strip()
        if cell in ('feature', 'idea', 'role'):
            continue
        if low == 'ideas':
            out['ideas'].add(am.slug(cell))
        elif low != 'roles':
            out['rows'].add(am.slug(cell))
    return out


# ------------------------------------------------------------------ check

def gaps(m, docs):
    """Coverage gaps of the merged model's features, one line each."""
    out = []
    feats = m['features']
    ops = {(o['term'], o['op']) for f in feats for o in f['ops']}
    screens = {s for f in feats for s in f['screens']}
    tasks = {t for f in feats for t in f['tasks']}
    for t in m['terms']:
        if t['kind'] != 'object' or (t.get('axes') or {}).get('origin') != 'user':
            continue
        for o in (t['axes'].get('operations') or []):
            op = o['op'] if isinstance(o, dict) else o
            if (t['id'], op) not in ops:
                out.append(f'op {t["id"]}:{op} is in no feature ops')
    for s in m['screens']:
        if s['kind'] == 'page' and set(s.get('seen_in') or []) & {'code', 'app'} and s['id'] not in screens:
            out.append(f'screen {s["id"]} ({s["route"]}) is in no feature screens')
    for t in m['tasks']:
        if t['id'] not in tasks:
            out.append(f'task {t["id"]} "{t["title"]}" is in no feature tasks')
    have = {f['id'] for f in feats}
    for f in (docs or {}).get('features') or []:
        if f['id'] not in have:
            out.append(f'docs feature {f["id"]} is missing (keep every docs feature id)')
    for f in feats:
        if not (f['evidence'] or f['tasks'] or f['ops']):
            out.append(f'feature {f["id"]} cites no task, op or doc row')
    return out


def check(d):
    d, m, _, docs = load_dir(d)
    out = gaps(m, docs)
    for g in out:
        print(g)
    if out:
        return 1
    print(f'ok: {len(m["features"])} features in {len(m["featuresets"])} featuresets cover every op, page and task')
    return 0


# ------------------------------------------------------------------ render

def sources_of(f, m, documented):
    """The sources a feature is seen in: its ops and screens, else its terms; docs also when the roster names it."""
    terms = {t['id']: t for t in m['terms']}
    screens = {s['id']: s for s in m['screens']}
    seen = set()
    for o in f['ops']:
        for x in (terms.get(o['term'], {}).get('axes') or {}).get('operations') or []:
            if isinstance(x, dict) and x['op'] == o['op']:
                seen.update(x.get('seen_in') or [])
    for s in f['screens']:
        seen.update(screens.get(s, {}).get('seen_in') or [])
    if not f['ops'] and not f['screens']:
        for t in f['terms']:
            seen.update(terms.get(t, {}).get('seen_in') or [])
    if documented:
        seen.add('docs')
    return seen


def status(seen, present):
    c, a, d = 'code' in seen, 'app' in seen, 'docs' in seen
    if 'code' not in present:
        c = a
    if 'app' not in present:
        a = c
    if not c and not a:
        return 'unbuilt' if d else None
    if not c:
        return 'ui-only'
    if not a:
        return 'hidden'
    return 'undocumented' if 'docs' in present and not d else 'built'


def cell(x):
    return str(x).replace('|', '\\|').replace('\n', ' ')


def render(d):
    d, m, present, docs = load_dir(d)
    r = roster(m['app'].get('root'))
    documented = {f['id'] for f in (docs or {}).get('features') or []} | r['rows'] | r['ideas']
    for f in m['features']:
        f['status'] = status(sources_of(f, m, f['id'] in documented), present)
    errors = am.validate(m)
    if errors:
        sys.exit('\n'.join(errors))
    am.save(d / 'app-model.merged.yaml', m)
    sha = m['provenance'].get('source_sha') or 'none'
    lines = ['---', f'last_updated: {today()}', f'source_sha: {sha}', '---', '',
             f'# Feature map: {m["app"]["name"]}', '',
             f'Derived by `app-model` from the merged model of {", ".join(present)}. Status: `built` in code and app, '
             '`hidden` in code but not reached in the app, `unbuilt` in docs only, `undocumented` in code or app but '
             'not in the docs, `ui-only` in the app with no code behind it.', '']
    by_fs = {}
    for f in m['features']:
        by_fs.setdefault(f['featureset'], []).append(f)
    for fs in m['featuresets']:
        lines += [f'## {fs["id"]}', '', fs['purpose'] or '', '',
                  '| feature | outcome | status | terms | screens | roles | evidence |', '|---|---|---|---|---|---|---|']
        for f in by_fs.get(fs['id'], []):
            ev = ', '.join(f'`{e["ref"]}`' for e in f['evidence'][:3]) + (' …' if len(f['evidence']) > 3 else '')
            lines.append(f'| <a id="{f["id"]}"></a>{f["id"]} | {cell(f["outcome"] or "")} | {f["status"] or "-"} '
                         f'| {", ".join(f["terms"]) or "-"} | {", ".join(f["screens"]) or "-"} '
                         f'| {", ".join(f["roles"]) or "-"} | {ev or "-"} |')
        lines.append('')
    counts = {s: 0 for s in (*STATUSES, None)}
    for f in m['features']:
        counts[f['status']] += 1
    lines += ['## Status', '', '| status | features |', '|---|---|']
    lines += [f'| {s or "unknown"} | {n} |' for s, n in counts.items()]
    lines += ['', '## Uncovered', '']
    rest = gaps(m, docs)
    lines += [f'- {g}' for g in rest] or ['None.']
    (d / 'feature-map.md').write_text('\n'.join(lines) + '\n', encoding='utf-8')
    print(f'feature-map.md: {len(m["features"])} features; '
          + ', '.join(f'{s or "unknown"}={n}' for s, n in counts.items() if n) + f'; uncovered: {len(rest)}')
    return 0


# ------------------------------------------------------------------ propose

def glossary_mode(repo):
    scope = Path(repo) / '_concept/01_meta/scope.yaml'
    if not scope.is_file():
        return None
    import yaml
    return (yaml.safe_load(scope.read_text(encoding='utf-8')) or {}).get('glossary')


def term_entry(t, date):
    seen = ', '.join({'code': 'the code', 'docs': 'the docs', 'app': 'the running app'}[s] for s in t.get('seen_in') or [])
    return [f'**{t["label"]}** (`{t["id"]}`):',
            t['definition'] or f'Found in {seen or "the merged model"}; no definition yet.',
            '- status: proposed', '- proposed_by: app-model', f'- proposed_on: {date}',
            f'- source: 02_grounding/findings/app-model/app-model.merged.yaml#{t["id"]}', f'- kind: {t["kind"]}', '']


def propose_ideas(m, r, date, rel):
    covered = r['rows'] | r['ideas'] | r['cut']
    rows = []
    for f in m['features']:
        if f['id'] in covered:
            continue
        fs = f['featureset'] if f['featureset'] in r['featuresets'] else f'{f["featureset"]} (new)'
        rows.append(f'| {f["id"]} | {fs} | `{rel}/feature-map.md#{f["id"]}` ({date}) | app-model |')
    if not rows:
        return []
    path, lines = r['path'], list(r['lines'])
    if not path.is_file():
        path.parent.mkdir(parents=True, exist_ok=True)
        lines = ['---', f'last_updated: {date}', '---', '', '# Featuresets', '', '## Ideas', '',
                 '| idea | featureset | source | raised_by |', '|---|---|---|---|', *rows]
    else:
        start = next((i for i, x in enumerate(lines) if x.strip().lower() == '## ideas'), None)
        if start is None:
            cut = next((i for i, x in enumerate(lines) if x.strip().lower() == '## cut'), len(lines))
            block = ['## Ideas', '', '| idea | featureset | source | raised_by |', '|---|---|---|---|', *rows, '']
            lines[cut:cut] = block
        else:
            end = next((i for i in range(start + 1, len(lines)) if lines[i].startswith('## ')), len(lines))
            last = max((i for i in range(start + 1, end) if lines[i].lstrip().startswith('|')), default=None)
            if last is None:
                lines[start + 1:start + 1] = ['', '| idea | featureset | source | raised_by |', '|---|---|---|---|', *rows]
            else:
                lines[last + 1:last + 1] = rows
    path.write_text('\n'.join(lines) + '\n', encoding='utf-8')
    return rows


def propose_terms(m, repo, d, date):
    """Merged terms the glossary lacks; app-only roles (app-explore personas) are no domain terms and are skipped."""
    mode = glossary_mode(repo)
    gpath = Path(repo) / '_concept/glossary.md'
    have = set()
    if mode == 'concept' and gpath.is_file():
        have = {mt.group(2) for x in gpath.read_text(encoding='utf-8').splitlines() if (mt := TERM.match(x.strip()))}
    else:
        docs = Path(d) / 'app-model.docs.yaml'
        have = {t['id'] for t in am.load(docs)['terms']} if docs.is_file() else set()
    new = [t for t in m['terms'] if t['id'] not in have
           and not (t['kind'] == 'role' and (t.get('seen_in') or []) == ['app'])]
    if not new:
        return mode, []
    entries = [x for t in new for x in term_entry(t, date)]
    if mode == 'concept' and gpath.is_file():
        lines = gpath.read_text(encoding='utf-8').splitlines()
        at = next((i for i, x in enumerate(lines) if x.strip() == '## Relations'), len(lines))
        lines[at:at] = entries
        gpath.write_text('\n'.join(lines) + '\n', encoding='utf-8')
    else:
        p = Path(d) / 'proposals.md'
        head = [] if p.is_file() else ['---', f'last_updated: {date}', '---', '', '# app-model: proposed glossary terms', '']
        old = p.read_text(encoding='utf-8').splitlines() if p.is_file() else []
        p.write_text('\n'.join(head + old + entries) + '\n', encoding='utf-8')
    return mode, [t['id'] for t in new]


def propose(d, repo):
    d, m, _, _ = load_dir(d)
    repo = Path(repo).resolve()
    date = today()
    try:
        rel = Path(d).resolve().relative_to(repo / '_concept').as_posix()
    except ValueError:
        rel = '02_grounding/findings/app-model'
    rows = propose_ideas(m, roster(repo), date, rel)
    mode, terms = propose_terms(m, repo, d, date)
    print(f'ideas: {len(rows)} rows appended to _concept/05_features/featuresets.md')
    if mode == 'concept':
        print(f'glossary: {len(terms)} proposed terms appended to _concept/glossary.md' + (f' ({", ".join(terms)})' if terms else ''))
    elif terms:
        print(f'glossary in {"split" if mode else "undecided"} mode: run concept-glossary with {d}/proposals.md '
              f'({len(terms)} terms)')
    return 0


def main(argv):
    if len(argv) == 3 and argv[1] in ('check', 'render'):
        return (check if argv[1] == 'check' else render)(argv[2])
    if len(argv) == 4 and argv[1] == 'propose':
        return propose(argv[2], argv[3])
    print(__doc__.strip(), file=sys.stderr)
    return 2


if __name__ == '__main__':
    sys.exit(main(sys.argv))
