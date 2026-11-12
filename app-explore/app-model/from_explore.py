#!/usr/bin/env python3
"""App source: an app-explore data dir (model.json + graph.json) as app-model.app.yaml.

Usage: $PY from_explore.py <stem>.data <out.yaml> [--repo <root>]
"""
import json
import re
import sys
from pathlib import Path

import model as am

OPS = {
    'create': {'create', 'new', 'add', 'neu', 'anlegen', 'hinzufügen'},
    'read': {'open', 'view', 'show', 'find', 'search', 'öffnen', 'suchen'},
    'edit': {'edit', 'rename', 'update', 'change', 'bearbeiten', 'ändern'},
    'delete': {'delete', 'remove', 'löschen', 'entfernen'},
    'archive': {'archive', 'archivieren'},
}
OP_ORDER = ['create', 'read', 'edit', 'delete', 'archive']
AS = {'list': 'row', 'table': 'row', 'card': 'card', 'chip': 'chip', 'detail': 'page', 'form': 'page'}
KINDS = {'page', 'dialog', 'menu', 'tab', 'drawer', 'popover'}


def op_of(verb):
    w = str(verb).strip().lower()
    for op, words in OPS.items():
        if w in words:
            return op
    return None


def convert(data_dir, repo=None):
    data = Path(data_dir).resolve()
    m = json.loads((data / 'model.json').read_text())
    g = json.loads((data / 'graph.json').read_text())
    run = {}
    if (data / 'run.json').exists():
        run = json.loads((data / 'run.json').read_text())
    url = run.get('url') or next((s.get('url') for s in g['states'] if s.get('url')), None)
    name = data.name.removesuffix('.data')
    out = am.empty('app', name, root=str(Path(repo).resolve()) if repo else None, url=url,
                   inputs=[str(data / 'model.json'), str(data / 'graph.json')], sha=am.git_head(repo),
                   made_by='app-model/from_explore')
    term_of = {}  # model object/persona id -> term id
    for o in m['objects']:
        oid = am.slug(o['name']) or am.slug(o['id'])
        term_of[o['id']] = f'{oid}-{am.slug(o["id"])}' if oid in term_of.values() else oid
    for p in m.get('personas', []):
        pid = am.slug(p['name']) or am.slug(p['id'])
        term_of[p['id']] = f'{pid}-role' if pid in term_of.values() else pid

    for o in m['objects']:
        ops = {op_of(c['verb']) for c in o.get('ctas', [])} - {None}
        homes = o.get('homes', [])
        out['terms'].append({
            'id': term_of[o['id']], 'label': o['name'],
            'aliases': [a for a in o.get('aliases', []) if am.slug(a) != term_of[o['id']]],
            'definition': None, 'kind': 'object', 'class': o.get('class'),
            'axes': {
                'navigation': 'primary' if o.get('class') == 'core' else 'contextual' if homes else 'none',
                'lifecycle': None,
                'origin': 'system' if o.get('class') == 'system' else 'user',
                'operations': [op for op in OP_ORDER if op in ops],
            },
            'attributes': [{'name': a, 'home': None} for a in o.get('attributes', [])],
            'evidence': [{'ref': f'state:{homes[0]}'}] if homes else [],
            'grade': 'inferred',
        })
    for p in m.get('personas', []):
        out['terms'].append({
            'id': term_of[p['id']], 'label': p['name'], 'aliases': [], 'definition': p.get('goal'),
            'kind': 'role', 'class': None, 'attributes': [], 'evidence': [{'ref': f'persona:{p["id"]}'}],
            'grade': 'inferred',
        })

    seen_rel = set()
    for o in m['objects']:
        for r in o.get('relationships', []):
            if r['to'] not in term_of:
                continue
            key = (term_of[o['id']], am.slug(r['as']), term_of[r['to']])
            if key in seen_rel or not key[1]:
                continue
            seen_rel.add(key)
            out['relations'].append({'subject': key[0], 'predicate': key[1], 'object': key[2],
                                     'evidence': [{'ref': f'state:{o["homes"][0]}'}] if o.get('homes') else [],
                                     'grade': 'inferred'})

    shows, actions = {}, {}
    for o in m['objects']:
        for rep in o.get('representations', []):
            a = AS.get(rep['as'])
            if a and {'term': term_of[o['id']], 'as': a} not in shows.setdefault(rep['state'], []):
                shows[rep['state']].append({'term': term_of[o['id']], 'as': a})
        for c in o.get('ctas', []):
            for st in c.get('states', []):
                actions.setdefault(st, []).append({'verb': c['verb'], 'term': term_of[o['id']], 'target': None})
    ids = set()
    for s in g['states']:
        ids.add(s['id'])
        out['screens'].append({
            'id': s['id'], 'route': s.get('route'), 'kind': s['kind'] if s.get('kind') in KINDS else 'page',
            'shows': shows.get(s['id'], []), 'actions': actions.get(s['id'], []),
            'evidence': [{'ref': f'state:{s["id"]}'}], 'grade': 'extracted',
        })
    for e in g['edges']:
        if e['from'] in ids and e['to'] in ids:
            out['navigation'].append({'from': e['from'], 'to': e['to'], 'label': e.get('label')})

    for t in m.get('tasks', []):
        tgt = t.get('target_state')
        out['tasks'].append({
            'id': am.slug(t['id']), 'title': t['title'], 'role': term_of.get(t.get('persona')),
            'verb': t['verb'], 'term': term_of.get(t.get('object')),
            'screens': [tgt] if tgt in ids else [],
            'evidence': [{'ref': f'walk:{t["id"]}'}], 'grade': 'inferred',
        })
    return out


def main(argv):
    args = argv[1:]
    repo = None
    if '--repo' in args:
        i = args.index('--repo')
        repo = args[i + 1]
        del args[i:i + 2]
    if len(args) != 2:
        print(__doc__.strip(), file=sys.stderr)
        return 2
    out = convert(args[0], repo)
    errors = am.validate(out)
    am.save(args[1], out)
    for e in errors:
        print(e)
    if errors:
        return 1
    print(f'{args[1]}: {am.counts(out)}')
    return 0


if __name__ == '__main__':
    sys.exit(main(sys.argv))
