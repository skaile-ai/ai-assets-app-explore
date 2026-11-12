#!/usr/bin/env python3
"""Compare app-model sources: align their terms, merge them, list what does not fit.

Usage:
  $PY compare.py candidates <dir>   YAML list of term pairs to decide, {a, b, why}
  $PY compare.py run <dir>          app-model.merged.yaml, compare.yaml, compare.md

<dir> holds app-model.{code,docs,app}.yaml (any one to three) and optionally align.yaml
`{same: [[a, b]], different: [[a, b]]}`, each side "<source>:<term id>".

Terms group automatically across sources when their slug sets {id, slug(label), slug(alias)…} intersect; a `same`
pair joins two groups, a `different` pair keeps two terms apart. Merge precedence and the mismatch rules are in
SKILL.md § Compare.
"""
import datetime
import difflib
import json
import re
import sys
from pathlib import Path

import yaml

import model as am

SOURCES = am.SOURCES
SEV = {'high': 0, 'medium': 1, 'low': 2}
OPS = ['create', 'read', 'edit', 'delete', 'archive']
# Function words a long alias carries ("settings for this section"): never evidence that two terms name one thing.
STOP_WORDS = frozenset('and are but can for from has its not of the this that with von und der die das den dem des ein eine fuer für mit oder aus bei'.split())


def first(*vals):
    return next((v for v in vals if v is not None), None)


def keys(t):
    return {k for k in [t['id'], am.slug(t['label'])] + [am.slug(a) for a in t.get('aliases') or []] if k}


def norm_route(r):
    if not r:
        return None
    segs = []
    for s in r.split('?')[0].split('#')[0].strip('/').split('/'):
        if re.fullmatch(r':[^/]+|\[[^\]]+\]|\{[^}]+\}|\d+|\*', s):
            s = '*'
        segs.append(s.lower())
    return '/' + '/'.join(x for x in segs if x)


class Sources:
    def __init__(self, d):
        self.dir = Path(d)
        self.m = {}
        for s in SOURCES:
            p = self.dir / f'app-model.{s}.yaml'
            if p.is_file():
                m = am.load(p)
                errs = am.validate(m)
                if errs:
                    raise SystemExit(f'{p}: invalid, run model.py validate:\n' + '\n'.join(errs[:10]))
                self.m[s] = m
        align = self.dir / 'align.yaml'
        a = am.load(align) if align.is_file() else {}
        a = a or {}
        self.same = [tuple(p) for p in a.get('same') or []]
        self.different = {frozenset(p) for p in a.get('different') or []}
        self.terms = {f'{s}:{t["id"]}': (s, t) for s, m in self.m.items() for t in m['terms']}
        for p in self.same + [tuple(x) for x in self.different]:
            for k in p:
                if k not in self.terms:
                    raise SystemExit(f'align.yaml: {k} names no term of the sources in {self.dir}')
        self.groups = self._group()

    def _group(self):
        parent = {k: k for k in self.terms}

        def find(x):
            while parent[x] != x:
                parent[x] = parent[parent[x]]
                x = parent[x]
            return x

        def union(a, b):
            parent[find(a)] = find(b)

        ks = {k: keys(t) for k, (_, t) in self.terms.items()}
        is_role = {k: t['kind'] == 'role' for k, (_, t) in self.terms.items()}
        names = list(self.terms)
        for i, a in enumerate(names):
            for b in names[i + 1:]:
                # A role never joins a non-role by a shared key alone ("Owner" as the signed-in user's name): that pair
                # stays a candidate and is decided in align.yaml.
                if (self.terms[a][0] != self.terms[b][0] and ks[a] & ks[b] and is_role[a] == is_role[b]
                        and frozenset((a, b)) not in self.different):
                    union(a, b)
        for a, b in self.same:
            union(a, b)
        groups = {}
        for k in names:
            groups.setdefault(find(k), []).append(k)
        return list(groups.values())

    def group_of(self):
        return {k: i for i, g in enumerate(self.groups) for k in g}

    def candidates(self):
        decided = {frozenset(p) for p in self.same} | self.different
        gi = self.group_of()
        out = []
        names = list(self.terms)
        for i, a in enumerate(names):
            for b in names[i + 1:]:
                sa, ta = self.terms[a]
                sb, tb = self.terms[b]
                if sa == sb or gi[a] == gi[b] or frozenset((a, b)) in decided:
                    continue
                why = None
                tok_a = {w for k in keys(ta) for w in k.split('-') if len(w) >= 3 and w not in STOP_WORDS}
                tok_b = {w for k in keys(tb) for w in k.split('-') if len(w) >= 3 and w not in STOP_WORDS}
                shared = sorted(tok_a & tok_b)
                if shared:
                    why = f'shared word {shared[0]}'
                else:
                    r = max(difflib.SequenceMatcher(None, x, y).ratio() for x in keys(ta) for y in keys(tb))
                    if r >= 0.75:
                        why = f'similar {r:.2f}'
                if why:
                    out.append({'a': a, 'b': b, 'why': why})
        return out


# ------------------------------------------------------------------ merge

class Merger:
    def __init__(self, src):
        self.src = src
        self.idmap = {s: {} for s in src.m}       # source -> source term id -> merged term id
        self.smap = {s: {} for s in src.m}        # source -> source screen id -> merged screen id
        self.tmap = {s: {} for s in src.m}        # source -> task id -> merged task id
        self.group = {}                           # merged id -> {source: [term]}
        self.home_src = {}                        # id(merged attribute) -> source its home came from

    def merge(self):
        src = self.src
        sha = next((m['provenance']['source_sha'] for s in ('code', 'docs', 'app') if (m := src.m.get(s))
                    and m['provenance']['source_sha'] != 'none'), 'none')
        any_m = next(iter(src.m.values()))
        root = first(*(m['app']['root'] for m in src.m.values()))
        url = first(*(m['app']['url'] for m in src.m.values()))
        name = (src.m.get('docs') or src.m.get('code') or any_m)['app']['name']
        out = am.empty('merged', name, root=root, url=url, sha=sha, made_by='app-model/compare',
                       inputs=[str((src.dir / f'app-model.{s}.yaml').resolve()) for s in src.m])
        used = set()
        for g in src.groups:
            by = {}
            for k in g:
                s, t = src.terms[k]
                by.setdefault(s, []).append(t)
            mid = next(by[s][0]['id'] for s in ('docs', 'code', 'app') if s in by)
            if mid in used:
                mid = f'{mid}-{next(s for s in ("docs", "code", "app") if s in by)}'
            used.add(mid)
            self.group[mid] = by
            for s, ts in by.items():
                for t in ts:
                    self.idmap[s][t['id']] = mid
        for mid, by in self.group.items():
            out['terms'].append(self.term(mid, by))
        self.relations(out)
        self.screens(out)
        self.tasks(out)
        self.features(out)
        return out

    @staticmethod
    def pick(by, order, get):
        for s in order:
            for t in by.get(s, []):
                v = get(t)
                if v is not None:
                    return v
        return None

    def term(self, mid, by):
        seen = [s for s in SOURCES if s in by]
        P = self.pick
        label = P(by, ('docs', 'app', 'code'), lambda t: t['label'])
        aliases, al_seen = [], {am.slug(label)}
        for s in seen:
            for t in by[s]:
                for a in [t['label']] + list(t.get('aliases') or []):
                    if am.slug(a) not in al_seen:
                        al_seen.add(am.slug(a))
                        aliases.append(a)
        kind = P(by, ('docs', 'code', 'app'), lambda t: t['kind'])
        t = {'id': mid, 'label': label, 'aliases': aliases,
             'definition': P(by, ('docs', 'code', 'app'), lambda t: t.get('definition')),
             'kind': kind, 'class': P(by, ('code', 'docs', 'app'), lambda t: t.get('class'))}
        if kind == 'object':
            ax = lambda k: (lambda t: (t.get('axes') or {}).get(k))
            lc = None
            for s in ('code', 'docs', 'app'):
                v = P({s: by.get(s, [])}, (s,), ax('lifecycle'))
                if v is not None:
                    if v.startswith('owned-by:'):
                        parent = self.idmap[s].get(v.split(':', 1)[1])
                        v = f'owned-by:{parent}' if parent else None
                    if v is not None:
                        lc = v
                        break
            ops = {}
            for s in seen:
                for x in by[s]:
                    for op in (x.get('axes') or {}).get('operations') or []:
                        ops.setdefault(op, [])
                        if s not in ops[op]:
                            ops[op].append(s)
            t['axes'] = {'navigation': P(by, ('app', 'code', 'docs'), ax('navigation')), 'lifecycle': lc,
                         'origin': P(by, ('code', 'docs', 'app'), ax('origin')),
                         'operations': [{'op': o, 'seen_in': ops[o]} for o in OPS if o in ops]}
        attrs = {}
        for s in ('code', 'app', 'docs'):
            for x in by.get(s, []):
                for a in x.get('attributes') or []:
                    k = am.slug(a['name']) or a['name']
                    e = attrs.setdefault(k, {'name': a['name'], 'home': None, 'seen_in': [], 'ids': {}})
                    if e['home'] is None and a.get('home') is not None:
                        e['home'] = a['home']
                        self.home_src[id(e)] = s
                    if s not in e['seen_in']:
                        e['seen_in'].append(s)
                    e['ids'].setdefault(s, a['name'])
        for e in attrs.values():
            e['seen_in'] = [s for s in SOURCES if s in e['seen_in']]
        t['attributes'] = list(attrs.values())
        t['evidence'] = [ev for s in seen for x in by[s] for ev in x.get('evidence') or []]
        grades = {x['grade'] for s in seen for x in by[s]}
        t['grade'] = 'extracted' if 'extracted' in grades else 'inferred' if 'inferred' in grades else 'needs_review'
        t['seen_in'] = seen
        t['ids'] = {s: by[s][0]['id'] for s in seen}
        return t

    def relations(self, out):
        rel = {}
        for s, m in self.src.m.items():
            for r in m['relations']:
                key = (self.idmap[s][r['subject']], r['predicate'], self.idmap[s][r['object']])
                e = rel.setdefault(key, {'subject': key[0], 'predicate': key[1], 'object': key[2], 'evidence': [],
                                         'grade': r['grade'], 'seen_in': [], 'ids': {}})
                e['evidence'] += r['evidence']
                if r['grade'] == 'extracted':
                    e['grade'] = 'extracted'
                if s not in e['seen_in']:
                    e['seen_in'].append(s)
                e['ids'][s] = f'{r["subject"]} · {r["predicate"]} · {r["object"]}'
        for e in rel.values():
            e['seen_in'] = [s for s in SOURCES if s in e['seen_in']]
        out['relations'] = list(rel.values())

    def screens(self, out):
        merged, by_route, used = [], {}, set()
        for s in ('docs', 'code', 'app'):
            m = self.src.m.get(s)
            if not m:
                continue
            for sc in m['screens']:
                nr = norm_route(sc['route']) if sc['kind'] == 'page' else None
                e = by_route.get(nr) if nr else None
                if e is None:
                    sid = sc['id'] if sc['id'] not in used else f'{s}-{sc["id"]}'[:48]
                    used.add(sid)
                    e = {'id': sid, 'route': sc['route'], 'kind': sc['kind'], 'shows': [], 'actions': [],
                         'evidence': [], 'grade': sc['grade'], 'seen_in': [], 'ids': {}}
                    merged.append(e)
                    if nr:
                        by_route[nr] = e
                self.smap[s][sc['id']] = e['id']
                if s not in e['seen_in']:
                    e['seen_in'].append(s)
                e['ids'][s] = sc['id']
                e['evidence'] += sc['evidence']
                if sc['grade'] == 'extracted':
                    e['grade'] = 'extracted'
                if s == 'code' and sc['route']:
                    e['route'] = sc['route']
        for s, m in self.src.m.items():
            for sc in m['screens']:
                e = next(x for x in merged if x['id'] == self.smap[s][sc['id']])
                for x in sc['shows']:
                    y = {'term': self.idmap[s][x['term']], 'as': x['as']}
                    if y not in e['shows']:
                        e['shows'].append(y)
                for a in sc['actions']:
                    y = {'verb': a['verb'], 'term': self.idmap[s].get(a['term']) if a['term'] else None,
                         'target': self.smap[s].get(a['target']) if a['target'] else None}
                    if y not in e['actions']:
                        e['actions'].append(y)
        for e in merged:
            e['seen_in'] = [s for s in SOURCES if s in e['seen_in']]
        out['screens'] = merged
        nav = []
        for s, m in self.src.m.items():
            for n in m['navigation']:
                y = {'from': self.smap[s][n['from']], 'to': self.smap[s][n['to']], 'label': n['label']}
                if y not in nav:
                    nav.append(y)
        out['navigation'] = nav
        ids = {e['id'] for e in merged}
        for t in out['terms']:
            for a in t['attributes']:
                home = a['home']
                if home in (None, 'none', 'several'):
                    continue
                src = self.home_src.get(id(a))
                a['home'] = self.smap.get(src, {}).get(home, home if home in ids else None)

    def tasks(self, out):
        """A task id held by several sources is one task (app-explore `seed` keeps the docs task ids): docs fields
        win, then code, then app; screens and evidence are the union."""
        by_id = {}
        for s in ('docs', 'code', 'app'):
            m = self.src.m.get(s)
            if not m:
                continue
            for t in m['tasks']:
                self.tmap[s][t['id']] = t['id']
                screens = [self.smap[s][x] for x in t['screens']]
                e = by_id.get(t['id'])
                if e is None:
                    by_id[t['id']] = {
                        'id': t['id'], 'title': t['title'], 'role': self.idmap[s].get(t['role']) if t['role'] else None,
                        'verb': t['verb'], 'term': self.idmap[s].get(t['term']) if t['term'] else None,
                        'screens': screens, 'evidence': list(t['evidence']), 'grade': t['grade'], 'seen_in': [s],
                        'ids': {s: t['id']}}
                    continue
                if e['role'] is None and t['role']:
                    e['role'] = self.idmap[s].get(t['role'])
                if e['term'] is None and t['term']:
                    e['term'] = self.idmap[s].get(t['term'])
                e['screens'] += [x for x in screens if x not in e['screens']]
                e['evidence'] += t['evidence']
                if t['grade'] != e['grade']:
                    e['grade'] = 'inferred' if 'needs_review' not in (t['grade'], e['grade']) else 'needs_review'
                e['seen_in'].append(s)
                e['ids'][s] = t['id']
        out['tasks'] = list(by_id.values())

    def features(self, out):
        fsets, feats = {}, {}
        for s in ('docs', 'code', 'app'):
            m = self.src.m.get(s)
            if not m:
                continue
            for fs in m['featuresets']:
                fsets.setdefault(fs['id'], dict(fs))
            for f in m['features']:
                if f['id'] in feats:
                    continue
                feats[f['id']] = {
                    **f, 'terms': [self.idmap[s][x] for x in f['terms']],
                    'ops': [{'term': self.idmap[s][o['term']], 'op': o['op']} for o in f['ops']],
                    'screens': [self.smap[s][x] for x in f['screens']],
                    'tasks': [self.tmap[s][x] for x in f['tasks']],
                    'roles': [self.idmap[s][x] for x in f['roles']]}
        out['featuresets'] = list(fsets.values())
        out['features'] = list(feats.values())


# ------------------------------------------------------------------ rules

class Rules:
    def __init__(self, src, mg, merged):
        self.src, self.mg, self.merged = src, mg, merged
        self.present = set(src.m)
        self.rows = []

    def add(self, rule, subject, sev, suggestion, text, values, evidence, confidence='high', key=None):
        self.rows.append({'id': f'{rule}:{key or subject}', 'rule': rule, 'subject': subject, 'sev': sev,
                          'confidence': confidence, 'suggestion': suggestion, 'text': text,
                          'values': values, 'evidence': evidence})

    @staticmethod
    def ev(ts):
        return [e['ref'] for t in ts for e in t.get('evidence') or []]

    def run(self):
        P = self.present
        for mid, by in self.mg.group.items():
            kinds = {s: by[s][0]['kind'] for s in by}
            if not any(k in ('object', 'role') for k in kinds.values()):
                continue
            obj = {s for s, k in kinds.items() if k == 'object'}
            label = lambda s: by[s][0]['label']
            evs = {s: self.ev(by[s]) for s in by}
            if 'code' in obj and 'app' in P and 'app' not in by:
                core = by['code'][0].get('class') == 'core'
                self.add('MM-only-code', mid, 'high' if core else 'medium', 'fix-ui',
                         f'{label("code")} is an object in the code but the running app never showed it',
                         {'code': label('code')}, {'code': evs['code']})
            if 'app' in obj and 'code' in P and 'code' not in by:
                self.add('MM-only-app', mid, 'medium', 'decide',
                         f'{label("app")} appears in the running app but no code object matches it',
                         {'app': label('app')}, {'app': evs['app']})
            if 'docs' in obj and P & {'code', 'app'} and not by.keys() & {'code', 'app'}:
                self.add('MM-only-docs', mid, 'medium', 'decide',
                         f'{label("docs")} is documented but neither the code nor the app has it',
                         {'docs': label('docs')}, {'docs': evs['docs']})
            if obj & {'code', 'app'} and 'docs' in P and 'docs' not in by:
                s = 'code' if 'code' in obj else 'app'
                self.add('MM-undocumented', mid, 'low', 'fix-docs',
                         f'{label(s)} exists in the {"code" if s == "code" else "running app"} but the docs do not name it',
                         {x: label(x) for x in by}, {x: evs[x] for x in by})
            if len({am.slug(label(s)) for s in by}) >= 2:
                self.add('MM-name', mid, 'medium', 'decide',
                         'one thing, several names: ' + ' / '.join(f'{label(s)} ({s})' for s in SOURCES if s in by),
                         {s: label(s) for s in by}, {s: evs[s] for s in by})
            cls = {s: by[s][0].get('class') for s in by if by[s][0].get('class')}
            if len(set(cls.values())) >= 2:
                self.add('MM-class', mid, 'medium', 'decide',
                         f'class differs: ' + ', '.join(f'{v} ({s})' for s, v in cls.items()), cls,
                         {s: evs[s] for s in cls})
            nav = {s: (by[s][0].get('axes') or {}).get('navigation') for s in obj}
            nav = {s: v for s, v in nav.items() if v}
            if len(set(nav.values())) >= 2:
                self.add('MM-navigation', mid, 'medium', 'decide',
                         'navigation differs: ' + ', '.join(f'{v} ({s})' for s, v in nav.items()), nav,
                         {s: evs[s] for s in nav})
            ops = {s: set((by[s][0].get('axes') or {}).get('operations') or []) for s in obj}
            for a, b, sev, sug in (('code', 'app', 'medium', 'fix-ui'), ('app', 'code', 'low', 'decide'),
                                   ('docs', 'code', 'medium', 'decide')):
                if a in ops and b in ops:
                    for op in sorted(ops[a] - ops[b], key=OPS.index):
                        self.add('MM-operation', mid, sev, sug,
                                 f'{op} {label(a)}: in {a}, not in {b}',
                                 {s: sorted(ops[s], key=OPS.index) for s in ops}, {a: evs[a], b: evs[b]},
                                 key=f'{mid}:{op}:{a}-{b}')
        self.relations()
        self.screens()
        self.tasks()
        self.rows.sort(key=lambda r: (SEV[r['sev']], r['rule'], r['id']))
        return self.rows

    def relations(self):
        kind = {t['id']: t['kind'] for t in self.merged['terms']}
        terms_in = {s: set(self.mg.idmap[s].values()) for s in self.src.m}
        pairs = {s: {} for s in self.src.m}
        for s, m in self.src.m.items():
            for r in m['relations']:
                a, b = self.mg.idmap[s][r['subject']], self.mg.idmap[s][r['object']]
                if a != b and kind.get(a) in ('object', 'role') and kind.get(b) in ('object', 'role'):
                    pairs[s].setdefault(frozenset((a, b)), []).append(r)
        done = set()
        for x in self.src.m:
            for y in self.src.m:
                if x == y:
                    continue
                for pair, rs in pairs[x].items():
                    if pair in pairs[y] or not pair <= terms_in[y] or pair in done:
                        continue
                    done.add(pair)
                    a, b = sorted(pair)
                    vals = {s: [f'{r["subject"]} · {r["predicate"]} · {r["object"]}' for r in pairs[s].get(pair, [])]
                            or None for s in self.src.m if pair <= terms_in[s]}
                    self.add('MM-relation', f'{a}~{b}', 'low', 'decide',
                             f'{a} and {b} are related in ' + ', '.join(s for s, v in vals.items() if v)
                             + ', not in ' + ', '.join(s for s, v in vals.items() if not v),
                             vals, {s: [e['ref'] for r in pairs[s].get(pair, []) for e in r['evidence']]
                                    for s in vals if vals[s]})

    def app_budget_hit(self):
        app = self.src.m.get('app')
        if not app:
            return False
        for i in app['provenance']['inputs']:
            d = Path(i).parent
            g, r = d / 'graph.json', d / 'run.json'
            if g.is_file() and r.is_file():
                try:
                    states = len(json.loads(g.read_text())['states'])
                    budget = (json.loads(r.read_text()).get('budgets') or {}).get('states')
                    return budget is not None and states >= budget
                except (ValueError, KeyError):
                    return False
        return False

    def screens(self):
        P = self.present
        pages = {s: {} for s in self.src.m}
        for s, m in self.src.m.items():
            for sc in m['screens']:
                if sc['kind'] == 'page' and sc['route']:
                    pages[s].setdefault(norm_route(sc['route']), sc)
        if 'code' in P and 'app' in P:
            low = self.app_budget_hit()
            for r, sc in pages['code'].items():
                if r not in pages['app']:
                    self.add('MM-screen-unreached', self.mg.smap['code'][sc['id']], 'medium', 'fix-ui',
                             f'code route {sc["route"]} was not reached in the running app'
                             + (' (the crawl stopped at its state budget)' if low else ''),
                             {'code': sc['route'], 'app': None}, {'code': [e['ref'] for e in sc['evidence']]},
                             confidence='low' if low else 'high')
            for r, sc in pages['app'].items():
                if r not in pages['code']:
                    self.add('MM-screen-unknown', self.mg.smap['app'][sc['id']], 'low', 'decide',
                             f'app route {sc["route"]} matches no code route',
                             {'code': None, 'app': sc['route']}, {'app': [e['ref'] for e in sc['evidence']]})

    def tasks(self):
        if 'app' not in self.present or 'docs' not in self.present:
            return
        in_app = {sc['id'] for sc in self.merged['screens'] if 'app' in sc['seen_in']}
        docs = self.src.m['docs']
        app_tasks = {t['id']: t for t in self.src.m['app']['tasks']}
        for kind, items in (('task', docs['tasks']), ('feature', docs['features'])):
            for t in items:
                walked = app_tasks.get(t['id']) if kind == 'task' else None
                if walked is not None:
                    # A seeded task: the app run looked for it, so its target screen is the verdict.
                    if not walked['screens']:
                        self.add('MM-task-unreachable', t['id'], 'medium', 'fix-ui',
                                 f'docs task {t["id"]} was walked in the app, which found no screen where it is done',
                                 {'docs': t['screens'], 'app': []},
                                 {'docs': [e['ref'] for e in t['evidence']], 'app': [e['ref'] for e in walked['evidence']]},
                                 key=f'task:{t["id"]}')
                    continue
                if not t['screens']:
                    continue
                ms = [self.mg.smap['docs'][x] for x in t['screens']]
                if not set(ms) & in_app:
                    self.add('MM-task-unreachable', t['id'], 'medium', 'fix-ui',
                             f'docs {kind} {t["id"]} needs screens {", ".join(t["screens"])}, none seen in the app',
                             {'docs': t['screens'], 'app': None}, {'docs': [e['ref'] for e in t['evidence']]},
                             key=f'{kind}:{t["id"]}')


# ------------------------------------------------------------------ output

def cell(v):
    if v is None:
        return '—'
    if isinstance(v, list):
        return ', '.join(str(x) for x in v) or '—'
    return str(v).replace('|', '\\|')


def write_md(path, merged, src, rows, undecided):
    today = datetime.date.today().isoformat()
    lines = ['---', f'last_updated: {today}', f'source_sha: {merged["provenance"]["source_sha"]}', '---', '',
             f'# app-model compare: {merged["app"]["name"]}', '',
             '| source | terms | objects | relations | screens | tasks | features |', '|---|---|---|---|---|---|---|']
    for s, m in list(src.m.items()) + [('merged', merged)]:
        objs = sum(1 for t in m['terms'] if t['kind'] == 'object')
        lines.append(f'| {s} | {len(m["terms"])} | {objs} | {len(m["relations"])} | {len(m["screens"])} '
                     f'| {len(m["tasks"])} | {len(m["features"])} |')
    by_rule = {}
    for r in rows:
        by_rule[r['rule']] = by_rule.get(r['rule'], 0) + 1
    lines += ['', '## Mismatches', '', '| rule | count |', '|---|---|']
    lines += [f'| {k} | {v} |' for k, v in sorted(by_rule.items())] or ['| — | 0 |']
    lines += ['', '| id | rule | sev | subject | code | docs | app | suggestion |', '|---|---|---|---|---|---|---|---|']
    for r in rows:
        v = r['values']
        sev = r['sev'] + (' (low confidence)' if r['confidence'] == 'low' else '')
        lines.append(f'| {cell(r["id"])} | {r["rule"]} | {sev} | {cell(r["subject"])} | {cell(v.get("code"))} '
                     f'| {cell(v.get("docs"))} | {cell(v.get("app"))} | {r["suggestion"]} |')
    lines += ['', '## Undecided pairs', '']
    lines += [f'- `{p["a"]}` ~ `{p["b"]}`: {p["why"]}' for p in undecided] or ['None.']
    Path(path).write_text('\n'.join(lines) + '\n', encoding='utf-8')


def run(d):
    src = Sources(d)
    if not src.m:
        print(f'compare: no app-model.{{code,docs,app}}.yaml in {d}')
        return 1
    mg = Merger(src)
    merged = mg.merge()
    errors = am.validate(merged)
    am.save(Path(d) / 'app-model.merged.yaml', merged)
    if errors:
        print('app-model.merged.yaml does not validate:\n' + '\n'.join(errors))
        return 1
    if len(src.m) < 2:
        print('compare: one source, nothing to compare')
        return 0
    rows = Rules(src, mg, merged).run()
    undecided = src.candidates()
    cmp = {'sources': [s for s in SOURCES if s in src.m], 'undecided': undecided, 'mismatches': rows}
    (Path(d) / 'compare.yaml').write_text(
        yaml.safe_dump(cmp, sort_keys=False, allow_unicode=True, width=120, default_flow_style=False), encoding='utf-8')
    write_md(Path(d) / 'compare.md', merged, src, rows, undecided)
    by_rule = {}
    for r in rows:
        by_rule[r['rule']] = by_rule.get(r['rule'], 0) + 1
    print(f'merged: {am.counts(merged)}; mismatches: {len(rows)} '
          + ' '.join(f'{k}={v}' for k, v in sorted(by_rule.items())) + f'; undecided: {len(undecided)}')
    return 0


def main(argv):
    if len(argv) == 3 and argv[1] == 'candidates':
        c = Sources(argv[2]).candidates()
        print(yaml.safe_dump(c, sort_keys=False, allow_unicode=True, width=120) if c else '[]')
        return 0
    if len(argv) == 3 and argv[1] == 'run':
        return run(argv[2])
    print(__doc__.strip(), file=sys.stderr)
    return 2


if __name__ == '__main__':
    sys.exit(main(sys.argv))
