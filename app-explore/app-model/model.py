#!/usr/bin/env python3
"""app-model/1 core: slug rule, load, validate, save.

Usage (PY="uv run --quiet --with pyyaml==6.0.3 python3"):
  $PY model.py validate <file.yaml>   ok line and exit 0, else one line per error and exit 1
  $PY model.py slug "<text>"          skaileup term id of <text>
  $PY model.py json <file.yaml>       the model as JSON on stdout

Structure checks follow schema/app-model.schema.json (a small draft 2020-12 subset: type, const, enum, pattern,
required, properties, additionalProperties, items, $ref, anyOf); reference and merged-file checks are below it.
"""
import datetime
import json
import re
import sys
from pathlib import Path

import yaml

HERE = Path(__file__).resolve().parent
SCHEMA_PATH = HERE / 'schema' / 'app-model.schema.json'
SOURCES = ('code', 'docs', 'app')
_SCHEMA = None


def schema():
    global _SCHEMA
    if _SCHEMA is None:
        _SCHEMA = json.loads(SCHEMA_PATH.read_text())
    return _SCHEMA


# ------------------------------------------------------------------ slug

_TRANSLIT = {'ä': 'ae', 'ö': 'oe', 'ü': 'ue', 'ß': 'ss'}


def slug(text):
    """skaileup term id (tree/glossary.md § Ids): lowercase, ä→ae ö→oe ü→ue ß→ss, runs outside [a-z0-9] → '-', trim '-'."""
    s = str(text).lower()
    s = ''.join(_TRANSLIT.get(c, c) for c in s)
    return re.sub(r'[^a-z0-9]+', '-', s).strip('-')


# ------------------------------------------------------------------ load / save

def _iso(v):
    if isinstance(v, (datetime.date, datetime.datetime)):
        return v.isoformat()
    if isinstance(v, dict):
        return {k: _iso(x) for k, x in v.items()}
    if isinstance(v, list):
        return [_iso(x) for x in v]
    return v


def load(path):
    """yaml.safe_load with date and datetime values turned into ISO text."""
    with open(path, encoding='utf-8') as f:
        return _iso(yaml.safe_load(f))


def dumps(model):
    head = f'# yaml-language-server: $schema={SCHEMA_PATH}\n'
    return head + yaml.safe_dump(model, sort_keys=False, allow_unicode=True, width=120, default_flow_style=False)


def save(path, model):
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    Path(path).write_text(dumps(model), encoding='utf-8')


def empty(source, name, root=None, url=None, inputs=(), sha='none', made_by='app-model'):
    """A valid model with no entries, keys in schema order."""
    return {
        'schema': 'app-model/1', 'source': source,
        'app': {'name': name, 'root': root, 'url': url},
        'provenance': {'made_by': made_by, 'made_on': datetime.date.today().isoformat(), 'source_sha': sha,
                       'inputs': list(inputs)},
        'terms': [], 'relations': [], 'screens': [], 'navigation': [], 'tasks': [], 'featuresets': [], 'features': [],
    }


def git_head(root):
    import subprocess
    if not root:
        return 'none'
    r = subprocess.run(['git', '-C', str(root), 'rev-parse', 'HEAD'], capture_output=True, text=True)
    return r.stdout.strip() if r.returncode == 0 else 'none'


def catalogue(out_dir):
    """When out_dir is skaileup's `_concept/02_grounding/findings/app-model/`, give every file in it a row
    `| app-model/<file> | <source> | <date> | app-model |` in `findings/index.md` (skaileup's findings
    catalogue), replacing that file's earlier row and keeping every other row. Returns the rows written."""
    d = Path(out_dir).resolve()
    if d.name != 'app-model' or d.parent.name != 'findings' or d.parent.parent.name != '02_grounding':
        return 0
    date = datetime.date.today().isoformat()
    rows = {}
    for f in sorted(p for p in d.iterdir() if p.is_file() and not p.name.startswith('.')):
        src = 'app-model.merged.yaml'
        m = re.fullmatch(r'app-model\.(code|docs|app)\.yaml', f.name)
        if m:
            try:
                ins = load(f)['provenance']['inputs'] or []
            except Exception:
                ins = []
            src = ', '.join(ins[:3]) + (' …' if len(ins) > 3 else '') or m.group(1)
        elif f.name == 'align.yaml':
            src = 'term pairs decided in the run'
        elif f.name == 'app-model.merged.yaml':
            src = ', '.join(p.name for p in sorted(d.glob('app-model.*.yaml')) if p.name != f.name)
        rows[f'app-model/{f.name}'] = f'| app-model/{f.name} | {src.replace("|", "/")} | {date} | app-model |'
    index = d.parent / 'index.md'
    if index.is_file():
        lines = index.read_text(encoding='utf-8').splitlines()
    else:
        lines = ['---', f'last_updated: {date}', '---', '', '# Findings', '', '| file | source | date | step |', '|---|---|---|---|']
    lines = [f'last_updated: {date}' if l.startswith('last_updated:') else l for l in lines]
    kept = [l for l in lines if not any(l.startswith(f'| {k} |') for k in rows)]
    at = max((i for i, l in enumerate(kept) if l.startswith('|')), default=len(kept) - 1) + 1
    if not any(l.startswith('| file |') for l in kept):
        kept[at:at] = ['', '| file | source | date | step |', '|---|---|---|---|']
        at += 3
    kept[at:at] = list(rows.values())
    index.write_text('\n'.join(kept) + '\n', encoding='utf-8')
    return len(rows)


# ------------------------------------------------------------------ structure

_PY_TYPE = {'string': str, 'boolean': bool, 'object': dict, 'array': list, 'null': type(None)}


def _tname(v):
    if v is None:
        return 'null'
    if isinstance(v, bool):
        return 'bool'
    if isinstance(v, (int, float)):
        return 'number'
    if isinstance(v, str):
        return 'string'
    if isinstance(v, list):
        return 'list'
    if isinstance(v, dict):
        return 'mapping'
    return type(v).__name__


def _is(v, t):
    if t == 'number':
        return isinstance(v, (int, float)) and not isinstance(v, bool)
    if t == 'integer':
        return isinstance(v, int) and not isinstance(v, bool)
    return isinstance(v, _PY_TYPE[t])


def _resolve(s):
    while '$ref' in s:
        s = schema()['$defs'][s['$ref'].split('/')[-1]]
    return s


def _check(v, s, path, out):
    s = _resolve(s)
    if 'anyOf' in s:
        for alt in s['anyOf']:
            sub = []
            _check(v, alt, path, sub)
            if not sub:
                return
        out.append(f'{path}: matches none of the allowed shapes, got {_tname(v)} {json.dumps(v, ensure_ascii=False, default=str)[:80]}')
        return
    if 'const' in s and v != s['const']:
        out.append(f'{path}: expected {s["const"]!r}, got {v!r}')
        return
    if 'enum' in s:
        if v not in s['enum']:
            want = ' | '.join('null' if e is None else str(e) for e in s['enum'])
            hint = ' (quote the value)' if isinstance(v, bool) else ''
            out.append(f'{path}: expected one of {want}, got {v!r}{hint}')
        return
    types = s.get('type')
    if types is not None:
        types = [types] if isinstance(types, str) else types
        if not any(_is(v, t) for t in types):
            if 'string' in types and isinstance(v, (bool, int, float)):
                out.append(f'{path}: expected string, got {_tname(v)} (quote the value)')
            else:
                out.append(f'{path or "<root>"}: expected {" or ".join(types)}, got {_tname(v)}')
            return
    if isinstance(v, str) and 'pattern' in s and not re.search(s['pattern'], v):
        out.append(f'{path}: {v!r} does not match {s["pattern"]}')
    if isinstance(v, dict):
        props = s.get('properties', {})
        for k in s.get('required', []):
            if k not in v:
                out.append(f'{path}: missing key {k}')
        for k, x in v.items():
            if k in props:
                _check(x, props[k], f'{path}.{k}' if path else k, out)
            elif s.get('additionalProperties') is False:
                out.append(f'{path or "<root>"}: unknown key {k}')
    if isinstance(v, list) and 'items' in s:
        for i, x in enumerate(v):
            _check(x, s['items'], f'{path}[{i}]', out)


# ------------------------------------------------------------------ references

def _where(kind, i, e, key='id'):
    return f'{kind}[{i}] ({e.get(key)})' if isinstance(e, dict) and e.get(key) is not None else f'{kind}[{i}]'


def _refs(m, out):
    def lst(k):
        x = m.get(k)
        return [e for e in x if isinstance(e, dict)] if isinstance(x, list) else []

    def ids_of(k):
        return [e.get('id') for e in lst(k)]

    for k in ('terms', 'screens', 'tasks', 'featuresets', 'features'):
        seen = set()
        for i in ids_of(k):
            if i in seen:
                out.append(f'{k}: duplicate id {i}')
            seen.add(i)
    terms, screens, tasks, fsets = (set(ids_of(k)) for k in ('terms', 'screens', 'tasks', 'featuresets'))
    kind = {e.get('id'): e.get('kind') for e in lst('terms')}

    def need(ids, val, where, what):
        if val is not None and val not in ids:
            out.append(f'{where}: unknown {what} {val}')

    for i, t in enumerate(lst('terms')):
        w = _where('terms', i, t)
        if 'axes' in t and t.get('kind') != 'object':
            out.append(f'{w}: axes only on kind object, this is kind {t.get("kind")}')
        lc = (t.get('axes') or {}).get('lifecycle') if isinstance(t.get('axes'), dict) else None
        if isinstance(lc, str) and lc.startswith('owned-by:'):
            need(terms, lc.split(':', 1)[1], f'{w}.axes.lifecycle', 'term')
    for i, r in enumerate(lst('relations')):
        w = f'relations[{i}] ({r.get("subject")} · {r.get("predicate")} · {r.get("object")})'
        need(terms, r.get('subject'), w, 'subject term')
        need(terms, r.get('object'), w, 'object term')
    for i, s in enumerate(lst('screens')):
        w = _where('screens', i, s)
        for j, x in enumerate(s.get('shows') or []):
            if isinstance(x, dict):
                need(terms, x.get('term'), f'{w}.shows[{j}]', 'term')
        for j, a in enumerate(s.get('actions') or []):
            if isinstance(a, dict):
                need(terms, a.get('term'), f'{w}.actions[{j}]', 'term')
                need(screens, a.get('target'), f'{w}.actions[{j}]', 'target screen')
    for i, e in enumerate(lst('navigation')):
        need(screens, e.get('from'), f'navigation[{i}]', 'from screen')
        need(screens, e.get('to'), f'navigation[{i}]', 'to screen')
    for i, t in enumerate(lst('tasks')):
        w = _where('tasks', i, t)
        need(terms, t.get('term'), w, 'term')
        need(terms, t.get('role'), w, 'role term')
        if t.get('role') in kind and kind[t.get('role')] != 'role':
            out.append(f'{w}: role {t.get("role")} is kind {kind[t.get("role")]}, not role')
        for x in t.get('screens') or []:
            need(screens, x, w, 'screen')
    for i, f in enumerate(lst('features')):
        w = _where('features', i, f)
        need(fsets, f.get('featureset'), w, 'featureset')
        for x in f.get('terms') or []:
            need(terms, x, f'{w}.terms', 'term')
        for x in f.get('ops') or []:
            if isinstance(x, dict):
                need(terms, x.get('term'), f'{w}.ops', 'term')
        for x in f.get('screens') or []:
            need(screens, x, f'{w}.screens', 'screen')
        for x in f.get('tasks') or []:
            need(tasks, x, f'{w}.tasks', 'task')
        for x in f.get('roles') or []:
            need(terms, x, f'{w}.roles', 'role term')


def _merged(m, out):
    merged = m.get('source') == 'merged'
    for k in ('terms', 'relations', 'screens', 'tasks'):
        for i, e in enumerate(m.get(k) or []):
            if not isinstance(e, dict):
                continue
            w = _where(k, i, e) if k != 'relations' else f'relations[{i}]'
            entries = [(w, e)] + [(f'{w}.attributes[{j}]', a) for j, a in enumerate(e.get('attributes') or [])
                                  if isinstance(a, dict)]
            for ww, x in entries:
                if merged and not x.get('seen_in'):
                    out.append(f'{ww}: merged file needs seen_in')
                if not merged:
                    for key in ('seen_in', 'ids'):
                        if key in x:
                            out.append(f'{ww}: {key} only in a merged file')
            ops = (e.get('axes') or {}).get('operations') if isinstance(e.get('axes'), dict) else None
            for j, op in enumerate(ops or []):
                if merged and not isinstance(op, dict):
                    out.append(f'{w}.axes.operations[{j}]: merged file writes {{op, seen_in}}, got {op!r}')
                if not merged and isinstance(op, dict):
                    out.append(f'{w}.axes.operations[{j}]: write the bare op, {{op, seen_in}} only in a merged file')


def validate(model):
    """Every structural, reference and merged-file error, one line each; [] when valid."""
    out = []
    _check(model, schema(), '', out)
    if isinstance(model, dict):
        _refs(model, out)
        _merged(model, out)
    return out


def counts(m):
    return ', '.join(f'{len(m.get(k) or [])} {k}' for k in ('terms', 'relations', 'screens', 'tasks', 'features'))


def main(argv):
    if len(argv) == 3 and argv[1] == 'slug':
        print(slug(argv[2]))
        return 0
    if len(argv) == 3 and argv[1] in ('validate', 'json'):
        try:
            m = load(argv[2])
        except (OSError, yaml.YAMLError) as e:
            print(f'{argv[2]}: {e}')
            return 1
        if argv[1] == 'json':
            print(json.dumps(m, ensure_ascii=False, indent=2))
            return 0
        errors = validate(m)
        for e in errors:
            print(e)
        if errors:
            return 1
        print(f'ok: {counts(m)}')
        return 0
    print(__doc__.strip(), file=sys.stderr)
    return 2


if __name__ == '__main__':
    sys.exit(main(sys.argv))
