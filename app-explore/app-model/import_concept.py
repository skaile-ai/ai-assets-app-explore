#!/usr/bin/env python3
"""Docs source, deterministic part: a repo's skaileup `_concept/` tree as app-model.docs.yaml.

Usage: $PY import_concept.py <repo root> <out.yaml>

Reads the glossary (concept mode: `_concept/glossary.md`; split mode: the project glossary for the words and
`_concept/glossary.md` for the ontology, mode per skaileup tree/glossary.md § Where the words live), the roster
`_concept/05_features/featuresets.md`, the feature specs `_concept/05_features/*/*.md` and the screens
`_concept/07_screens/*.md`. Every entry is `grade: extracted`; a missing file is listed in provenance.inputs as
`<path> (absent)`. References the tree makes to things it does not define are dropped and named on stderr.
"""
import re
import sys
from pathlib import Path

import yaml

import model as am

TERM = re.compile(r'^\*\*(.+?)\*\*(?:\s*\(`([^`]+)`\))?:\s*$')
LINE = re.compile(r'^- ([a-z-]+):\s*(.*)$')
OPS = ['create', 'read', 'edit', 'delete', 'archive']
SKIP_SECTIONS = {'roles', 'ideas', 'cut'}


def frontmatter(path):
    text = path.read_text(encoding='utf-8')
    if not text.startswith('---\n'):
        return {}, text
    end = text.find('\n---', 4)
    if end < 0:
        return {}, text
    data = yaml.safe_load(text[4:end]) or {}
    return am._iso(data), text


class Importer:
    def __init__(self, root):
        self.root = Path(root).resolve()
        self.inputs, self.warnings = [], []

    def rel(self, p):
        return str(Path(p).resolve().relative_to(self.root))

    def note(self, p):
        """Record a read; returns whether the file exists."""
        p = Path(p)
        ok = p.is_file()
        self.inputs.append(self.rel(p) if ok else f'{self.rel(p)} (absent)')
        return ok

    # -------------------------------------------------------------- glossary

    def mode(self):
        """('concept' | 'split', project glossary path or None)."""
        scope = self.root / '_concept/01_meta/scope.yaml'
        value = None
        if self.note(scope):
            value = (am._iso(yaml.safe_load(scope.read_text(encoding='utf-8'))) or {}).get('glossary')
        if value == 'concept':
            return 'concept', None
        if isinstance(value, str) and value and not value.startswith('/') and '..' not in value:
            return 'split', self.root / value
        for name in ('GLOSSARY.md', 'CONTEXT.md'):
            if (self.root / name).is_file():
                return 'split', self.root / name
        return 'concept', None

    def parse_glossary(self, path):
        """{id: entry} with label, definition, avoid, lines {key: (value, lineno)}, line."""
        out = {}
        rels = []
        cur = None
        section = None
        lines = path.read_text(encoding='utf-8').splitlines()
        in_front = bool(lines and lines[0] == '---')
        for n, raw in enumerate(lines, 1):
            line = raw.rstrip()
            if in_front:
                if n > 1 and line == '---':
                    in_front = False
                continue
            if line.startswith('## '):
                section = line[3:].strip().lower()
                cur = None
                continue
            if section == 'relations':
                m = re.match(r'^- (\S+)\s*·\s*(\S+)\s*·\s*(\S+)\s*$', line)
                if m:
                    rels.append((m.group(1), m.group(2), m.group(3), n))
                continue
            m = TERM.match(line)
            if m:
                label = m.group(1).strip()
                tid = m.group(2) or am.slug(label)
                cur = out.setdefault(tid, {'label': label, 'definition': None, 'avoid': [], 'lines': {}, 'line': n})
                continue
            if cur is None or not line:
                if not line:
                    cur = cur if cur and not cur['lines'] and cur['definition'] is None else None
                continue
            if line.startswith('_Avoid_:'):
                cur['avoid'] = [w.strip() for w in line[len('_Avoid_:'):].split(',') if w.strip()]
                continue
            m = LINE.match(line)
            if m:
                cur['lines'][m.group(1)] = (m.group(2).strip(), n)
            elif cur['definition'] is None and not cur['lines']:
                cur['definition'] = line.strip()
        return out, rels

    def glossary(self, out):
        mode, words = self.mode()
        onto_path = self.root / '_concept/glossary.md'
        onto, rels = ({}, [])
        if self.note(onto_path):
            onto, rels = self.parse_glossary(onto_path)
        word = {}
        if mode == 'split' and words is not None and self.note(words):
            word, _ = self.parse_glossary(words)
        onto_rel = self.rel(onto_path)
        ids = list(onto) + [i for i in word if i not in onto]
        label_to_id = {}
        for tid in ids:
            o, w = onto.get(tid, {}), word.get(tid, {})
            label_to_id[am.slug((w or o)['label'])] = tid
        for tid in ids:
            o, w = onto.get(tid), word.get(tid)
            src = w or o
            lines = (o or {}).get('lines', {})
            kind = lines.get('kind', ('concept', 0))[0]
            if kind not in ('object', 'role', 'event', 'state', 'value', 'concept'):
                self.warnings.append(f'{tid}: kind {kind!r} unknown, read as concept')
                kind = 'concept'
            ev = []
            if o:
                ev.append({'ref': f'{onto_rel}:{o["line"]}'})
            if w:
                ev.append({'ref': f'{self.rel(words)}:{w["line"]}'})
            t = {'id': tid, 'label': src['label'], 'aliases': src.get('avoid', []),
                 'definition': src.get('definition'), 'kind': kind, 'class': None}
            if kind == 'object':
                t['axes'] = self.axes(lines, label_to_id)
            t.update({'attributes': [], 'evidence': ev, 'grade': 'extracted'})
            out['terms'].append(t)
            for key in ('is-a', 'part-of'):
                v, n = lines.get(key, ('', 0))
                if v and v not in ('—', '-'):
                    rels.append((tid, key, label_to_id.get(am.slug(v), am.slug(v)), n))
        known = set(ids)
        seen = set()
        for s, p, ob, n in rels:
            if s not in known or ob not in known:
                self.warnings.append(f'{onto_rel}:{n}: relation {s} · {p} · {ob} names an unknown term, dropped')
                continue
            if (s, am.slug(p), ob) in seen:
                continue
            seen.add((s, am.slug(p), ob))
            out['relations'].append({'subject': s, 'predicate': am.slug(p), 'object': ob,
                                     'evidence': [{'ref': f'{onto_rel}:{n}'}], 'grade': 'extracted'})

    @staticmethod
    def axes(lines, label_to_id):
        def val(k, allowed):
            v = lines.get(k, (None, 0))[0]
            return v if v in allowed else None
        lc = lines.get('lifecycle', (None, 0))[0]
        if lc and lc.startswith('owned-by'):
            target = lc[len('owned-by'):].strip(' :')
            lc = f'owned-by:{label_to_id.get(am.slug(target), am.slug(target))}'
        elif lc not in ('independent', 'link'):
            lc = None
        ops_raw = lines.get('operations', ('', 0))[0]
        ops = {w.strip() for w in re.split(r'[·,]', ops_raw) if w.strip()}
        return {'navigation': val('navigation', ('primary', 'contextual', 'none')), 'lifecycle': lc,
                'origin': val('origin', ('user', 'system', 'derived')), 'operations': [o for o in OPS if o in ops]}

    # -------------------------------------------------------------- roster, specs, screens

    def screens(self, out):
        d = self.root / '_concept/07_screens'
        files = sorted(p for p in d.glob('*.md') if p.stem not in ('shell', 'README')) if d.is_dir() else []
        if not d.is_dir():
            self.inputs.append(f'{self.rel(d)}/*.md (absent)')
        terms = {t['id'] for t in out['terms']}
        for p in files:
            self.note(p)
            fm, _ = frontmatter(p)
            sid = fm.get('screen_id') or p.stem
            shows = []
            for region in (fm.get('regions') or {}).values():
                if not isinstance(region, dict):
                    continue
                term, rep = region.get('shows'), region.get('representation')
                if term in terms and rep in ('row', 'card', 'chip', 'peek', 'page'):
                    if {'term': term, 'as': rep} not in shows:
                        shows.append({'term': term, 'as': rep})
                elif term:
                    self.warnings.append(f'{self.rel(p)}: region shows {term!r} ({rep}) not a term or representation, dropped')
            out['screens'].append({'id': sid, 'route': fm.get('route'), 'kind': 'page', 'shows': shows, 'actions': [],
                                   'evidence': [{'ref': f'{self.rel(p)}:1'}], 'grade': 'extracted'})

    def roster(self, out):
        path = self.root / '_concept/05_features/featuresets.md'
        if not self.note(path):
            return
        rel = self.rel(path)
        fs = None
        want_purpose = False
        for n, raw in enumerate(path.read_text(encoding='utf-8').splitlines(), 1):
            line = raw.strip()
            if line.startswith('## '):
                name = line[3:].strip()
                fs = None
                if name.lower() in SKIP_SECTIONS or am.slug(name) != name:
                    continue
                fs = {'id': name, 'purpose': ''}
                out['featuresets'].append(fs)
                want_purpose = True
                continue
            if fs is None or not line:
                continue
            if want_purpose and not line.startswith('|'):
                fs['purpose'] = line
                want_purpose = False
                continue
            want_purpose = False
            cells = [c.strip() for c in line.strip('|').split('|')]
            if not line.startswith('|') or not cells or cells[0] in ('feature', '') or set(cells[0]) <= set('-:'):
                continue
            out['features'].append({
                'id': am.slug(cells[0]), 'featureset': fs['id'], 'outcome': cells[1] if len(cells) > 1 else None,
                'terms': [], 'ops': [], 'screens': [], 'tasks': [], 'roles': [], 'status': None,
                'evidence': [{'ref': f'{rel}:{n}'}], 'grade': 'extracted'})

    def entity_terms(self):
        """{model entity name: glossary term id} from the data model's `glossary` fields (else slug of display/name)."""
        path = self.root / '_concept/10_blueprint/datamodel/model.yaml'
        if not path.is_file():
            return {}
        data = yaml.safe_load(path.read_text(encoding='utf-8')) or {}
        out = {}
        for name, e in (data.get('entities') or {}).items():
            e = e or {}
            out[name] = e.get('glossary') or am.slug(e.get('display') or name)
        return out

    def specs(self, out):
        base = self.root / '_concept/05_features'
        by_id = {f['id']: f for f in out['features']}
        terms = {t['id']: t for t in out['terms']}
        screens = {s['id'] for s in out['screens']}
        entity = self.entity_terms()
        for p in sorted(base.glob('*/*.md')) if base.is_dir() else []:
            f = by_id.get(p.stem)
            if f is None or p.parent.name == '[featureset]':
                continue
            self.note(p)
            fm, _ = frontmatter(p)
            for name in fm.get('data_entities') or []:
                tid = entity.get(name, am.slug(name))
                if tid in terms and tid not in f['terms']:
                    f['terms'].append(tid)
                elif tid not in terms:
                    self.warnings.append(f'{self.rel(p)}: data entity {name} has no glossary term, dropped')
            for s in fm.get('screens') or []:
                sid = Path(s.get('path', '') if isinstance(s, dict) else str(s)).stem
                if sid in screens and sid not in f['screens']:
                    f['screens'].append(sid)
                elif sid not in screens:
                    self.warnings.append(f'{self.rel(p)}: screen {sid} has no 07_screens file, dropped')
            for r in fm.get('roles') or []:
                rid = am.slug(r)
                if terms.get(rid, {}).get('kind') == 'role' and rid not in f['roles']:
                    f['roles'].append(rid)
                elif rid != 'all-users':
                    self.warnings.append(f'{self.rel(p)}: role {r} is no role term, dropped')
            f['evidence'].append({'ref': f'{self.rel(p)}:1'})

    def run(self):
        out = am.empty('docs', self.root.name, root=str(self.root), sha=am.git_head(self.root),
                       made_by='app-model/import_concept')
        self.glossary(out)
        self.screens(out)
        self.roster(out)
        self.specs(out)
        out['provenance']['inputs'] = self.inputs
        return out


def main(argv):
    if len(argv) != 3:
        print(__doc__.strip(), file=sys.stderr)
        return 2
    imp = Importer(argv[1])
    out = imp.run()
    for w in imp.warnings:
        print(f'warning: {w}', file=sys.stderr)
    errors = am.validate(out)
    am.save(argv[2], out)
    for e in errors:
        print(e)
    if errors:
        return 1
    print(f'{argv[2]}: {am.counts(out)}, {len(out["featuresets"])} featuresets')
    return 0


if __name__ == '__main__':
    sys.exit(main(sys.argv))
