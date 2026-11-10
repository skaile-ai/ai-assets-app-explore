#!/usr/bin/env python3
"""Turn one app-explore run into report blocks.

    python3 compose.py <stem>.data <stem>.media

Reads graph.json, perceive.json, model.json, scent.json, run.json and the collections analyze.py wrote
(screens.json, objects.json, tasks.json, findings.json, scores.json, needs_check.json) and writes
<stem>.data/blocks.json = {entities, badges, stats, blocks: {<name>: block}} plus <stem>.data/findings_serious.json
(findings with sev >= 3, the collection behind the "serious findings" stat).

The report file sits next to <stem>.media/, so every gallery `src` is `<stem>.media/<file>`.
A block whose data is empty (no naming conflicts, no tasks, nothing to check) is left out of `blocks`.

With diff.json (analyze.py --since) the output is a change document (report `since`): blocks.json gets top-level
`since` = the previous stem; gallery items carry `change` new/changed (changed ones `before` = the previous shot) and
every removed screen is appended as a `removed` item showing its previous shot (`<prev stem>.media/<file>`, relative
to the report) with the notes of its fixed findings; finding entities carry `change: new`, fixed findings come back
as `removed` entities; `status_table` counts fixed / open / new findings per severity.

Report-build constraints this file follows (report skill build.py):
- One `tree` per report: every root entity with `tree` != false renders in it, so a second tree would render each
  anchor twice. Findings own the tree (filter `sev`); objects live in `objects_table` rows (anchor `o-<id>`), tasks in
  `tasks_table` rows (`t-<id>`), screens in `screens_gallery` items (`s-<id>`).
- One colour per meaning across all badge categories, and a value on under 5 % (or over 60 % without `default`) of
  10+ entities is a lint: `sev` bands merge rare neighbours and set `default` from the data.
- Inline text from models is defused (`[[` and `[@` would become links or citations).
"""
import json
import os
import re
import sys
from collections import Counter, defaultdict, deque
from pathlib import Path

SEV_COLORS = {4: "red", 3: "orange", 2: "yellow", 1: "gray", 0: "gray"}
CLASS_COLORS = {"core": "navy", "supporting": "teal", "child": "teal", "system": "brown"}
CLARITY_COLORS = {"good": "green", "fair": "blue", "poor": "pink"}
SCREEN_TYPE_COLOR = "purple"

T = {
    "en": {
        "sev": "Severity", "class": "Object class", "screen_type": "Screen type", "clarity": "Clarity",
        "sev_names": {4: "critical", 3: "major", 2: "minor", 1: "cosmetic", 0: "note"},
        "clarity_names": {"good": "clear (75+)", "fair": "fair (50-74)", "poor": "unclear (<50)"},
        "class_names": {"core": "core", "supporting": "supporting", "child": "child", "system": "system"},
        "stat_screens": "Screens", "stat_objects": "Objects", "stat_tasks": "Tasks", "stat_serious": "Serious findings",
        "where": "Where", "source": "Source", "confidence": "Confidence", "task": "task", "object": "object",
        "o_cols": ["Object", "Class", "Shown as", "Also called", "Screens", "Findings"],
        "n_cols": ["Object", "Names used", "Where"],
        "t_cols": ["Task", "Persona", "Object", "Target screen", "Shortest path", "First click", "Walk", "Clicks", "Ease"],
        "cta_cols": ["Action", "Where"],
        "s_cols": ["Task", "Start screen", "Predicted first click", "Shortest path starts with", "Confidence", "Result"],
        "sc_cols": ["Screen", "Type", "Clarity", "Hierarchy (0-3)", "Primary action", "Heading fits", "Location shown",
                    "Density", "Labels", "Findings"],
        "nc_cols": ["Screen", "Question", "Leaning", "Would raise", "Why unsure"],
        "f_cols": {"id": "Finding", "sev": "Severity", "rule": "Problem", "source": "Source", "screen": "Screen",
                   "text": "Evidence", "confidence": "Confidence", "status": "Since last run"},
        "status_cols": ["Severity", "Fixed", "Still open", "New"], "total": "Total",
        "status_names": {"open": "open", "new": "new", "fixed": "fixed"},
        "attrs": "Attributes", "related": "Related", "as": "as",
        "yes": "yes", "no": "no", "unsure": "unsure", "correct": "correct", "wrong": "wrong",
        "walk_ok": "succeeded", "walk_fail": "failed", "walk_none": "not walked",
        "clicks": "{n} clicks", "click": "1 click", "unreachable": "not reachable",
        "tree_count": "findings shown", "tree_hint": "Filter by severity; each finding links to its screen.",
        "map_label": "Screens and the clicks between them", "gallery_label": "Screens",
        "cta_label": "Actions per object", "k_nav": "navigates", "k_open": "opens",
        "depth_line": "depth {d}", "clar_line": "clarity {c}", "data_label": "All findings",
        "kind": {"page": "page", "dialog": "dialog", "menu": "menu", "tab": "tab"},
        "source_names": {"rubric": "screen judge", "geometry": "layout measure", "naming": "naming", "walk": "task walk",
                         "scent": "first click", "critic": "expert critique", "depth": "click depth", "leak": "write leak"},
    },
    "de": {
        "sev": "Schweregrad", "class": "Objektklasse", "screen_type": "Screen-Art", "clarity": "Klarheit",
        "sev_names": {4: "kritisch", 3: "schwer", 2: "mittel", 1: "kosmetisch", 0: "Hinweis"},
        "clarity_names": {"good": "klar (75+)", "fair": "mittel (50-74)", "poor": "unklar (<50)"},
        "class_names": {"core": "Kern", "supporting": "unterstützend", "child": "Teil", "system": "System"},
        "stat_screens": "Screens", "stat_objects": "Objekte", "stat_tasks": "Aufgaben", "stat_serious": "Schwere Befunde",
        "where": "Ort", "source": "Quelle", "confidence": "Sicherheit", "task": "Aufgabe", "object": "Objekt",
        "o_cols": ["Objekt", "Klasse", "Gezeigt als", "Auch genannt", "Screens", "Befunde"],
        "n_cols": ["Objekt", "Verwendete Namen", "Ort"],
        "t_cols": ["Aufgabe", "Persona", "Objekt", "Ziel-Screen", "Kürzester Weg", "Erster Klick", "Durchlauf", "Klicks",
                   "Leichtigkeit"],
        "cta_cols": ["Aktion", "Ort"],
        "s_cols": ["Aufgabe", "Start-Screen", "Vorhergesagter erster Klick", "Kürzester Weg beginnt mit", "Sicherheit",
                   "Ergebnis"],
        "sc_cols": ["Screen", "Art", "Klarheit", "Hierarchie (0-3)", "Hauptaktion", "Überschrift passt", "Ort erkennbar",
                    "Dichte", "Beschriftung", "Befunde"],
        "nc_cols": ["Screen", "Frage", "Tendenz", "Würde auslösen", "Warum unsicher"],
        "f_cols": {"id": "Befund", "sev": "Schweregrad", "rule": "Problem", "source": "Quelle", "screen": "Screen",
                   "text": "Beleg", "confidence": "Sicherheit", "status": "Seit letztem Lauf"},
        "status_cols": ["Schweregrad", "Behoben", "Noch offen", "Neu"], "total": "Gesamt",
        "status_names": {"open": "offen", "new": "neu", "fixed": "behoben"},
        "attrs": "Attribute", "related": "Verwandt", "as": "als",
        "yes": "ja", "no": "nein", "unsure": "unsicher", "correct": "richtig", "wrong": "falsch",
        "walk_ok": "geschafft", "walk_fail": "gescheitert", "walk_none": "nicht gelaufen",
        "clicks": "{n} Klicks", "click": "1 Klick", "unreachable": "nicht erreichbar",
        "tree_count": "Befunde sichtbar", "tree_hint": "Nach Schweregrad filtern; jeder Befund verweist auf seinen Screen.",
        "map_label": "Screens und die Klicks zwischen ihnen", "gallery_label": "Screens",
        "cta_label": "Aktionen je Objekt", "k_nav": "navigiert", "k_open": "öffnet",
        "depth_line": "Tiefe {d}", "clar_line": "Klarheit {c}", "data_label": "Alle Befunde",
        "kind": {"page": "Seite", "dialog": "Dialog", "menu": "Menü", "tab": "Tab"},
        "source_names": {"rubric": "Screen-Urteil", "geometry": "Layout-Messung", "naming": "Benennung", "walk": "Aufgabenlauf",
                         "scent": "erster Klick", "critic": "Expertenkritik", "depth": "Klicktiefe", "leak": "Schreibleck"},
    },
}

RULES = {
    "R-hierarchy": ("No clear visual hierarchy", "Keine klare visuelle Hierarchie"),
    "R-primary-competing": ("Competing primary actions", "Konkurrierende Hauptaktionen"),
    "R-primary-missing": ("No visible primary action", "Keine sichtbare Hauptaktion"),
    "R-title": ("Heading does not name the screen", "Überschrift benennt den Screen nicht"),
    "R-location": ("Location not shown", "Ort nicht erkennbar"),
    "R-density": ("Crowded screen", "Überladener Screen"),
    "R-labels": ("Jargon or unclear labels", "Fachjargon oder unklare Beschriftung"),
    "R-icon-only": ("Icon-only actions", "Aktionen nur als Icon"),
    "G-overflow": ("Text overflows its box", "Text läuft über"),
    "G-overlap": ("Overlapping controls", "Überlappende Elemente"),
    "G-target": ("Small click targets", "Kleine Klickflächen"),
    "N-naming": ("One object, several names", "Ein Objekt, mehrere Namen"),
    "D-depth": ("Task buried deep", "Aufgabe tief versteckt"),
    "W-failed": ("Task walk failed", "Aufgabe nicht geschafft"),
    "W-struggle": ("Task walk with detours", "Aufgabe mit Umwegen"),
    "S-scent": ("Wrong first click", "Falscher erster Klick"),
    "X-write-leak": ("Write reached the server", "Schreibzugriff erreichte den Server"),
}
NIELSEN = [
    ("Visibility of system status", "Sichtbarkeit des Systemstatus"),
    ("Match with the real world", "Übereinstimmung mit der realen Welt"),
    ("User control and freedom", "Kontrolle und Freiheit"),
    ("Consistency and standards", "Konsistenz und Standards"),
    ("Error prevention", "Fehlervermeidung"),
    ("Recognition rather than recall", "Wiedererkennen statt Erinnern"),
    ("Flexibility and efficiency", "Flexibilität und Effizienz"),
    ("Aesthetic and minimalist design", "Ästhetisches, minimalistisches Design"),
    ("Recovery from errors", "Hilfe bei Fehlern"),
    ("Help and documentation", "Hilfe und Dokumentation"),
]
VALUES_DE = {
    "landing": "Startseite", "list": "Liste", "detail": "Detail", "form": "Formular", "dashboard": "Dashboard",
    "settings": "Einstellungen", "dialog": "Dialog", "empty": "leer", "error": "Fehler",
    "one-clear": "eine klare", "several-competing": "mehrere konkurrierend", "none-visible": "keine sichtbar",
    "sparse": "spärlich", "balanced": "ausgewogen", "crowded": "überladen",
    "plain-words": "klare Worte", "some-jargon": "etwas Jargon", "jargon-or-icon-only": "Jargon oder nur Icons",
    "card": "Karte", "table": "Tabelle", "chip": "Chip", "menu-item": "Menüeintrag",
}
GATE = 0.6


def load(d, name, default):
    p = d / name
    return json.loads(p.read_text()) if p.is_file() else default


def safe(s):
    """Model text as report inline text: `[[` / `[@` would turn into links or citations; newlines into one line."""
    s = " ".join(str(s or "").split())
    return s.replace("[[", "[ [").replace("[@", "[ @")


def slug(s):
    return re.sub(r"[^a-z0-9]+", "-", str(s).lower()).strip("-") or "x"


def fid(f):
    return "f-" + slug(f["id"])


def oid(o):
    return "o-" + slug(o)


class Compose:
    def __init__(self, data, media):
        self.data, self.media = data, media
        run = load(data, "run.json", {})
        self.lang = "de" if str(run.get("lang", "en")).startswith("de") else "en"
        self.t = T[self.lang]
        self.graph = load(data, "graph.json", None)
        if not self.graph or not self.graph.get("states"):
            sys.exit(f"compose: {data}/graph.json has no states")
        self.perceive = load(data, "perceive.json", {})
        self.scent = load(data, "scent.json", {})
        self.findings = load(data, "findings.json", [])
        self.scores = load(data, "scores.json", {})
        self.needs = load(data, "needs_check.json", [])
        self.objects = load(data, "objects.json", None)
        self.tasks = load(data, "tasks.json", None)
        self.screens = load(data, "screens.json", None)
        if self.objects is None or self.tasks is None or self.screens is None:
            sys.exit(f"compose: run analyze.py first ({data} lacks screens.json, objects.json or tasks.json)")
        self.states = {s["id"]: s for s in self.graph["states"]}
        self.srow = {s["id"]: s for s in self.screens}
        self.obj_ids = {o["id"] for o in self.objects}
        self.task_ids = {t["id"] for t in self.tasks}
        self.order = self.bfs_order()
        self.marks = {}
        self.prev = self.load_prev(load(data, "diff.json", None))
        self.fixed = self.fixed_findings()

    def load_prev(self, diff):
        """The previous run behind diff.json: its stem, data dir, states, findings, and its media dir as the report
        (next to this run's media dir) must write it. None without diff.json."""
        if not diff:
            return None
        pdata = Path(diff["since_data"])
        pmedia = pdata.with_name(pdata.name[:-5] + ".media") if pdata.name.endswith(".data") else None
        pgraph = load(pdata, "graph.json", None) if pdata.is_dir() else None
        if pgraph is None or pmedia is None or not pmedia.is_dir():
            sys.exit(f"since: {pdata} has no .data/ dir (and .media/ beside it)")
        return {"diff": diff, "data": pdata, "media": pmedia,
                "media_rel": Path(os.path.relpath(pmedia.resolve(), self.media.parent.resolve())).as_posix(),
                "states": {s["id"]: s for s in pgraph["states"]},
                "findings": load(pdata, "findings.json", []),
                "changed": {c["id"]: c for c in diff["screens"]["changed"]},
                "new": set(diff["screens"]["new"]), "removed": diff["screens"]["removed"],
                "fixed": set(diff["findings"]["fixed"])}

    def prev_shot(self, pid):
        shot = Path(self.prev["states"][pid].get("shot") or f"{pid}.png").name
        if not (self.prev["media"] / shot).is_file():
            sys.exit(f"compose: missing previous screenshot {self.prev['media'] / shot}")
        return f"{self.prev['media_rel']}/{shot}"

    def fixed_findings(self):
        """Previous findings analyze.py marked fixed, minus any whose entity id a current finding already uses."""
        if not self.prev:
            return []
        now = {fid(f) for f in self.findings}
        return [f for f in self.prev["findings"] if f["id"] in self.prev["fixed"] and fid(f) not in now]

    @staticmethod
    def was(pid):
        """Entity id of a removed screen (previous state ids can be reused by other screens in this run)."""
        return "s-was-" + slug(pid)

    # -- helpers ---------------------------------------------------------
    def val(self, v):
        if v is None:
            return "—"
        v = str(v)
        return VALUES_DE.get(v, v).replace("-", " ") if self.lang == "de" else v.replace("-", " ")

    def rule_label(self, rule):
        i = 0 if self.lang == "en" else 1
        if rule in RULES:
            return RULES[rule][i]
        m = re.fullmatch(r"C-0*(\d+)", str(rule))
        if m and 1 <= int(m.group(1)) <= 10:
            return NIELSEN[int(m.group(1)) - 1][i]
        return str(rule)

    def bfs_order(self):
        """State ids in BFS order from the first state over graph edges; unreachable states keep graph order at the end."""
        ids = [s["id"] for s in self.graph["states"]]
        adj = defaultdict(list)
        for e in self.graph.get("edges", []):
            adj[e["from"]].append(e["to"])
        seen, out, q = {ids[0]}, [], deque([ids[0]])
        while q:
            u = q.popleft()
            out.append(u)
            for v in adj[u]:
                if v in self.states and v not in seen:
                    seen.add(v)
                    q.append(v)
        return out + [i for i in ids if i not in seen]

    def title(self, sid, states=None):
        states = states or self.states
        s = states[sid]
        if s.get("heading"):
            base = s["heading"]
        else:
            p = states.get(s.get("parent") or "")
            base = (p.get("heading") if p else None) or s.get("title") or s.get("route") or sid
            if s.get("kind", "page") != "page":
                base = f"{base} · {self.t['kind'].get(s['kind'], s['kind'])}"
        return " ".join(str(base).split())[:80]

    def screen_ref(self, sid):
        return {"ref": "s-" + sid} if sid in self.states else "—"

    def mark_info(self, sid, n, data=None):
        data = data or self.data
        if (data, sid) not in self.marks:
            p = data / "screens" / f"{sid}.json"
            self.marks[data, sid] = {m["n"]: m for m in (json.loads(p.read_text()).get("marks", []) if p.is_file() else [])}
        return self.marks[data, sid].get(n)

    def mark_label(self, sid, n):
        if n is None:
            return "—"
        m = self.mark_info(sid, n)
        return f"#{n} {safe(m.get('label') or m.get('role') or '')}".strip() if m else f"#{n}"

    def gate_choice(self, a):
        if not isinstance(a, dict) or a.get("choice") is None:
            return None, False
        p = max((a.get("probabilities") or {}).values(), default=a.get("confidence", 1))
        return a["choice"], p >= GATE

    def gate_bool(self, a):
        if not isinstance(a, dict) or not isinstance(a.get("bool"), (int, float)):
            return "—"
        p = a["bool"]
        return self.t["yes"] if p >= GATE else self.t["no"] if p <= 1 - GATE else self.t["unsure"]

    def band(self, c):
        if c is None:
            return None
        return "good" if c >= 75 else "fair" if c >= 50 else "poor"

    # -- badges and entities --------------------------------------------
    def sev_bands(self):
        """Severity badge values: one per sev in use; a value on under 5 % of 10+ findings merges into its larger
        neighbour so the build's rarity lint holds. Returns ({sev: value key}, values dict, default)."""
        cnt = Counter(int(f.get("sev", 0)) for f in self.findings + self.fixed)
        groups = [[s] for s in sorted(cnt, reverse=True)]
        n = sum(cnt.values())
        size = lambda g: sum(cnt[s] for s in g)
        while n >= 10 and len(groups) > 1:
            rare = [i for i, g in enumerate(groups) if size(g) * 100 / n < 5]
            if not rare:
                break
            i = rare[0]
            nb = [j for j in (i - 1, i + 1) if 0 <= j < len(groups)]
            j = max(nb, key=lambda j: size(groups[j]))
            a, b = sorted((i, j))
            groups[a:b + 1] = [groups[a] + groups[b]]
        key_of, values = {}, {}
        for g in groups:
            hi, lo = max(g), min(g)
            k = f"s{hi}" if hi == lo else f"s{lo}-{hi}"
            names = self.t["sev_names"]
            label = f"S{hi} {names[hi]}" if hi == lo else f"S{lo}–{hi}"
            values[k] = {"label": label, "color": SEV_COLORS.get(hi, "gray")}
            for s in g:
                key_of[s] = k
        default = None
        if n >= 10:
            top = max(groups, key=size)
            if size(top) * 100 / n > 60:
                default = key_of[top[0]]
        return key_of, values, default

    def badges(self, sev_values, sev_default, classes, types, bands):
        t = self.t
        b = {}
        if sev_values:
            b["sev"] = {"label": t["sev"], "shape": "square", "filter": "any", "values": sev_values}
            if sev_default:
                b["sev"]["default"] = sev_default
        if classes:
            b["class"] = {"label": t["class"], "shape": "pill", "values": {
                c: {"label": t["class_names"].get(c, c), "color": CLASS_COLORS.get(c, "teal")} for c in classes}}
        if types:
            b["screen_type"] = {"label": t["screen_type"], "shape": "text", "values": {
                v: {"label": self.val(v), "color": SCREEN_TYPE_COLOR} for v in types}}
        if bands:
            b["clarity"] = {"label": t["clarity"], "shape": "round", "values": {
                v: {"label": t["clarity_names"][v], "color": CLARITY_COLORS[v]} for v in bands}}
        return b

    # -- blocks ----------------------------------------------------------
    def objects_table(self):
        t, rows = self.t, []
        for o in self.objects:
            aliases = [a for a in o.get("aliases") or [] if a and a != o.get("name")]
            homes = [h for h in o.get("homes") or [] if h in self.states]
            rows.append({"anchor": oid(o["id"]), "cells": [
                safe(o.get("name") or o["id"]),
                {"badge": ["class", o["class"]]} if o.get("class") else "—",
                ", ".join(self.val(a) for a in o.get("shown_as") or []) or "—",
                ", ".join(safe(a) for a in aliases) or "—",
                {"refs": ["s-" + h for h in homes]} if homes else "—",
                int(o.get("findings") or 0)]})
        return {"type": "table", "columns": t["o_cols"], "numeric": [5], "rows": rows}

    def naming_table(self):
        rows = []
        for o in self.objects:
            names = [o.get("name")] + [a for a in o.get("aliases") or [] if a != o.get("name")]
            if int(o.get("labels") or len(set(names))) < 2:
                continue
            where = sorted({r["state"] for r in o.get("representations") or [] if r.get("state") in self.states}
                           | {h for h in o.get("homes") or [] if h in self.states})
            rows.append([{"ref": oid(o["id"])}, " / ".join(f"„{safe(n)}“" if self.lang == "de" else f"“{safe(n)}”" for n in names if n),
                         {"refs": ["s-" + s for s in where]} if where else "—"])
        return {"type": "table", "columns": self.t["n_cols"], "rows": rows} if rows else None

    def tasks_table(self):
        t, rows = self.t, []
        for k in self.tasks:
            sh = k.get("shortest")
            short = t["unreachable"] if sh is None else t["click"] if sh == 1 else t["clicks"].format(n=sh)
            sc = k.get("scent_correct")
            first = "—" if sc is None else t["correct"] if sc else t["wrong"]
            walk = t["walk_none"] if not k.get("walked") else t["walk_ok"] if k.get("success") else t["walk_fail"]
            rows.append({"anchor": "t-" + k["id"], "cells": [
                safe(k.get("title")), safe(k.get("persona_name") or k.get("persona") or "—"),
                {"ref": oid(k["object"])} if k.get("object") in self.obj_ids else safe(k.get("object") or "—"),
                self.screen_ref(k.get("target_state")), short, first, walk,
                k["clicks"] if isinstance(k.get("clicks"), int) else "—",
                f"{k['ease']}/5" if k.get("ease") is not None else "—"]})
        return {"type": "table", "columns": t["t_cols"], "rows": rows} if rows else None

    def cta_tabs(self):
        t, tabs = self.t, []
        for o in self.objects:
            ctas = o.get("ctas") or []
            parts = []
            if o.get("attributes"):
                parts.append(f"{t['attrs']}: " + ", ".join(safe(a) for a in o["attributes"]) + ".")
            rel = [r for r in o.get("relationships") or [] if r.get("to") in self.obj_ids and r.get("to") != o["id"]]
            if rel:
                parts.append(f"{t['related']}: " + ", ".join(
                    f"[[{oid(r['to'])}]]" + (f" ({t['as']} {safe(r['as'])})" if r.get("as") else "") for r in rel) + ".")
            rows = []
            for c in ctas:
                st = [s for s in c.get("states") or [] if s in self.states]
                rows.append([safe(c.get("verb") or "—"), {"refs": ["s-" + s for s in st]} if st else "—"])
            if not rows and not parts:
                continue
            tab = {"label": safe(o.get("name") or o["id"])[:40], "summary": f"[[{oid(o['id'])}]]. " + " ".join(parts)}
            tab["blocks"] = [{"type": "table", "columns": t["cta_cols"], "rows": rows}] if rows else []
            tabs.append(tab)
        return {"type": "tabs", "id": "ctas", "label": t["cta_label"], "tabs": tabs} if tabs else None

    def nav_map(self):
        t = self.t
        nodes = []
        for sid in self.order:
            s, r = self.states[sid], self.srow.get(sid, {})
            lines = []
            if r.get("depth") is not None:
                lines.append(t["depth_line"].format(d=r["depth"]))
            if r.get("clarity") is not None:
                lines.append(t["clar_line"].format(c=r["clarity"]))
            node = {"id": sid, "label": self.title(sid), "sub": s.get("route") or "/", "ref": "s-" + sid}
            if lines:
                node["lines"] = [" · ".join(lines)]
            if s.get("kind", "page") != "page":
                node["shape"] = "external"
            nodes.append(node)
        labels = {}
        for e in self.graph.get("edges", []):
            if e["from"] in self.states and e["to"] in self.states and e["from"] != e["to"]:
                labs = labels.setdefault((e["from"], e["to"]), [])
                lab = safe(e.get("label") or "")[:40]
                if lab and lab not in labs:
                    labs.append(lab)
        edges = []
        for (a, b), labs in labels.items():
            kind = "nav" if self.states[b].get("kind", "page") == "page" else "open"
            e = {"from": a, "to": b, "kind": kind}
            if labs:
                e["label"] = labs[0] if len(labs) == 1 else labs[:2]
            edges.append(e)
        return {"type": "map", "id": "nav", "label": t["map_label"], "nodes": nodes, "edges": edges,
                "kinds": {"nav": {"label": t["k_nav"], "color": "ink"}, "open": {"label": t["k_open"], "color": "gray", "dash": "dot"}}}

    def depth_bars(self):
        t = self.t
        cnt = Counter(r.get("depth") for r in self.screens)
        items = []
        for d in sorted(k for k in cnt if k is not None):
            items.append([t["click"] if d == 1 else t["clicks"].format(n=d), cnt[d], "ink"])
        if cnt.get(None):
            items.append([t["unreachable"], cnt[None], "gray"])
        return {"type": "bars", "items": items, "link": False} if items else None

    def scent_table(self):
        t, rows = self.t, []
        for k in self.tasks:
            s = self.scent.get(k["id"])
            if not s:
                continue
            entry = s.get("entry")
            ok = s.get("correct")
            p = s.get("p")
            rows.append([{"ref": "t-" + k["id"]}, self.screen_ref(entry), self.mark_label(entry, s.get("predicted_mark")),
                         self.mark_label(entry, s.get("shortest_first_mark")),
                         f"{round(p * 100)} %" if isinstance(p, (int, float)) else "—",
                         "—" if ok is None else t["correct"] if ok else t["wrong"]])
        return {"type": "table", "columns": t["s_cols"], "rows": rows} if rows else None

    def scorecard_table(self):
        t, rows = self.t, []
        scr = sorted(self.screens, key=lambda r: (r.get("clarity") is None, r.get("clarity") or 0))
        for r in scr:
            a = ((self.perceive.get(r["id"]) or {}).get("answers")) or {}
            h = a.get("hierarchy") if isinstance(a.get("hierarchy"), dict) else {}
            hs = h.get("score")

            def ch(q):
                v, ok = self.gate_choice(a.get(q))
                return "—" if v is None else self.val(v) + ("" if ok else " (?)")
            rows.append([{"ref": "s-" + r["id"]}, self.val(r.get("screen_type")) if r.get("screen_type") else "—",
                         r["clarity"] if r.get("clarity") is not None else "—",
                         round(hs, 1) if isinstance(hs, (int, float)) else "—",
                         ch("primary_action"), self.gate_bool(a.get("title_matches")), self.gate_bool(a.get("location")),
                         ch("density"), ch("labels"), int(r.get("findings") or 0)])
        return {"type": "table", "columns": t["sc_cols"], "numeric": [2, 3, 9], "rows": rows}

    def rubric_bars(self):
        cnt, top = Counter(), {}
        for f in self.findings:
            cnt[f["rule"]] += 1
            top[f["rule"]] = max(top.get(f["rule"], 0), int(f.get("sev", 0)))
        items = [[self.rule_label(r), n, SEV_COLORS.get(top[r], "gray")] for r, n in
                 sorted(cnt.items(), key=lambda x: (-top[x[0]], -x[1], x[0]))]
        return {"type": "bars", "items": items, "link": False} if items else None

    def finding_entities(self, key_of):
        """Rows of the findings tree; with `since` new ones carry `change: new` and fixed ones return as `removed`."""
        t, ents = self.t, []
        back = {p: c for c, p in self.prev["diff"]["match"].items()} if self.prev else {}
        for i, (f, fixed) in enumerate([(f, False) for f in self.findings] + [(f, True) for f in self.fixed]):
            where, title = [], self.rule_label(f["rule"])
            sid = back.get(f.get("state")) if fixed else f.get("state")
            if sid in self.states:
                where.append(f"[[s-{sid}]]")
                title = f"{title} · {self.title(sid)}"
            elif fixed and f.get("state") in self.prev["states"]:
                where.append(f"[[{self.was(f['state'])}]]")
                title = f"{title} · {self.title(f['state'], self.prev['states'])}"
            if f.get("object") in self.obj_ids:
                where.append(f"{t['object']} [[{oid(f['object'])}]]")
            for k in f.get("tasks") or []:
                if k in self.task_ids:
                    where.append(f"{t['task']} [[t-{k}]]")
            conf = f.get("confidence")
            # Every meta line is `<label>: <value>`: build.py turns a repeated key into one headed tree column, and an
            # unlabelled line repeated on two rows (the same rule text) would become a column of its own. The finding
            # text stays in `findings_data`: as a narrow tree column it makes the tree thousands of pixels tall.
            meta = [f"{t['where']}: " + (", ".join(where) or "—"),
                    f"{t['source']}: {t['source_names'].get(f.get('source'), safe(f.get('source') or '—'))}",
                    f"{t['confidence']}: " + (f"{round(conf * 100)} %" if isinstance(conf, (int, float)) else "—")]
            e = {"id": fid(f), "title": title, "order": i, "badges": {"sev": [key_of[int(f.get("sev", 0))]]}, "meta": meta}
            if fixed:
                e["change"] = "removed"
            elif self.prev and f.get("status") == "new":
                e["change"] = "new"
            ents.append(e)
        return ents

    def findings_data(self):
        t, c = self.t, self.t["f_cols"]
        cols = [{"label": c["id"], "key": "id"}, {"label": c["sev"], "key": "sev", "type": "number"},
                {"label": c["rule"], "key": "rule"}, {"label": c["source"], "key": "source"},
                {"label": c["screen"], "key": "screen"}, {"label": c["text"], "key": "text"},
                {"label": c["confidence"], "key": "confidence", "type": "number"}]
        if self.prev:
            cols.insert(2, {"label": c["status"], "key": "status"})
        rows = [{"id": fid(f), "sev": int(f.get("sev", 0)), "rule": self.rule_label(f["rule"]),
                 "source": t["source_names"].get(f.get("source"), safe(f.get("source") or "")),
                 "screen": self.screen_ref(f.get("state")), "text": safe(f.get("text")),
                 "confidence": round(f["confidence"], 2) if isinstance(f.get("confidence"), (int, float)) else None,
                 **({"status": t["status_names"].get(f.get("status"), "—")} if self.prev else {})}
                for f in self.findings]
        return {"type": "data", "id": "findings", "label": t["data_label"], "key": "id", "columns": cols, "rows": rows,
                "page": 25} if rows else None

    def status_table(self):
        """Findings per severity since the previous run: fixed / still open / new, worst severity first."""
        if not self.prev:
            return None
        cnt = defaultdict(Counter)
        for f in self.findings:
            cnt[int(f.get("sev", 0))][f.get("status", "new")] += 1
        for f in self.fixed:
            cnt[int(f.get("sev", 0))]["fixed"] += 1
        names = self.t["sev_names"]
        rows = [[f"S{s} {names[s]}", c["fixed"], c["open"], c["new"]] for s, c in sorted(cnt.items(), reverse=True)]
        tot = [sum(c[k] for c in cnt.values()) for k in ("fixed", "open", "new")]
        rows.append([self.t["total"], *tot])
        return {"type": "table", "columns": self.t["status_cols"], "numeric": [1, 2, 3], "rows": rows}

    def note(self, f, data=None):
        """One gallery note per finding: a box around its marks (pin at the box corner) when the screen file has them,
        else the pin analyze.py placed (mark centre, or 4/4 without marks). `data` = the run the finding belongs to."""
        boxes = [m["box"] for m in (self.mark_info(f["state"], n, data) for n in f.get("marks") or []) if m and m.get("box")]
        clamp = lambda v: round(min(max(float(v), 0), 100), 1)
        if boxes:
            x0 = min(b["x"] for b in boxes)
            y0 = min(b["y"] for b in boxes)
            x1 = max(b["x"] + b["w"] for b in boxes)
            y1 = max(b["y"] + b["h"] for b in boxes)
            n = {"x": clamp(x0), "y": clamp(y0), "w": clamp(min(x1, 100) - clamp(x0)), "h": clamp(min(y1, 100) - clamp(y0))}
        else:
            pin = (f.get("pins") or f.get("notes") or [{"x": 4, "y": 4}])[0]
            n = {"x": clamp(pin.get("x", 4)), "y": clamp(pin.get("y", 4))}
        n["text"] = f"{self.rule_label(f['rule'])}: {safe(f.get('text'))}" if f.get("text") else self.rule_label(f["rule"])
        n["sev"] = int(f.get("sev", 0))
        n["ref"] = fid(f)
        return n

    def screens_gallery(self):
        by_state = defaultdict(list)
        for f in self.findings:
            if f.get("state") in self.states:
                by_state[f["state"]].append(f)
        items = []
        for sid in self.order:
            s, r = self.states[sid], self.srow.get(sid, {})
            shot = Path(s.get("shot") or f"{sid}.png").name
            if not (self.media / shot).is_file():
                sys.exit(f"compose: missing screenshot {self.media / shot}")
            it = {"src": f"{self.media.name}/{shot}", "title": self.title(sid), "entity": "s-" + sid}
            purpose = r.get("purpose") or ((self.perceive.get(sid) or {}).get("extract") or {}).get("purpose")
            if purpose:
                it["caption"] = safe(purpose)
            badges = {}
            if r.get("screen_type"):
                badges["screen_type"] = [r["screen_type"]]
            if self.band(r.get("clarity")):
                badges["clarity"] = [self.band(r["clarity"])]
            if badges:
                it["badges"] = badges
            fs = sorted(by_state[sid], key=lambda f: -int(f.get("sev", 0)))
            if fs:
                it["notes"] = [self.note(f) for f in fs]
            if self.prev:
                if sid in self.prev["new"]:
                    it["change"] = "new"
                elif sid in self.prev["changed"]:
                    it["change"] = "changed"
                    it["before"] = self.prev_shot(self.prev["changed"][sid]["prev"])
            items.append(it)
        if self.prev:  # removed screens stay, struck through, with their previous shot and their (now fixed) findings
            fixed = defaultdict(list)
            for f in self.fixed:
                fixed[f.get("state")].append(f)
            for pid in self.prev["removed"]:
                it = {"src": self.prev_shot(pid), "title": self.title(pid, self.prev["states"]), "entity": self.was(pid),
                      "change": "removed"}
                fs = sorted(fixed[pid], key=lambda f: -int(f.get("sev", 0)))
                if fs:
                    it["notes"] = [self.note(f, self.prev["data"]) for f in fs]
                items.append(it)
        return {"type": "gallery", "label": self.t["gallery_label"], "items": items}

    def needs_check_table(self):
        rows = []
        for n in self.needs:
            q = n.get("question")
            qlabel = self.rule_label(q) if str(q).startswith("C-") else safe(q).replace("_", " ")
            lean = n.get("leaning")
            rows.append([self.screen_ref(n.get("state")), qlabel,
                         "—" if lean is None else self.val(lean) if isinstance(lean, str) else self.t["yes"] if lean else self.t["no"],
                         ", ".join(self.rule_label(r) for r in n.get("rules") or []) or "—", safe(n.get("text") or "—")])
        return {"type": "table", "columns": self.t["nc_cols"], "rows": rows} if rows else None

    # -- assemble --------------------------------------------------------
    def run(self):
        t = self.t
        for f in self.findings:  # the tree and the notes need these keys
            for k in ("id", "rule"):
                if not f.get(k):
                    sys.exit(f"compose: finding without `{k}`: {json.dumps(f)[:200]}")
        key_of, sev_values, sev_default = self.sev_bands()
        classes = [c for c in dict.fromkeys(o.get("class") for o in self.objects) if c]
        types = [v for v in dict.fromkeys(self.srow.get(s, {}).get("screen_type") for s in self.order) if v]
        bands = [b for b in ("good", "fair", "poor") if any(self.band(r.get("clarity")) == b for r in self.screens)]

        entities = []
        for o in self.objects:
            entities.append({"id": oid(o["id"]), "title": safe(o.get("name") or o["id"]), "tree": False})
        for k in self.tasks:
            entities.append({"id": "t-" + k["id"], "title": safe(k.get("title") or k["id"]), "tree": False})
        for sid in self.order:
            entities.append({"id": "s-" + sid, "title": self.title(sid), "tree": False})
        for pid in (self.prev or {}).get("removed", []):
            entities.append({"id": self.was(pid), "title": self.title(pid, self.prev["states"]), "tree": False})
        entities += self.finding_entities(key_of)

        blocks = {
            "objects_table": self.objects_table() if self.objects else None,
            "naming_table": self.naming_table(),
            "tasks_table": self.tasks_table(),
            "cta_tabs": self.cta_tabs(),
            "nav_map": self.nav_map(),
            "depth_bars": self.depth_bars(),
            "scent_table": self.scent_table(),
            "scorecard_table": self.scorecard_table(),
            "rubric_bars": self.rubric_bars(),
            "findings_tree": {"type": "tree", "filter": ["sev"], "count_label": t["tree_count"], "hint": t["tree_hint"]}
            if self.findings or self.fixed else None,
            "findings_data": self.findings_data(),
            "screens_gallery": self.screens_gallery(),
            "needs_check_table": self.needs_check_table(),
            "status_table": self.status_table(),
        }
        blocks = {k: v for k, v in blocks.items() if v is not None}

        serious = [f for f in self.findings if int(f.get("sev", 0)) >= 3]
        (self.data / "findings_serious.json").write_text(json.dumps(serious, ensure_ascii=False, indent=1))
        stats = [[t["stat_screens"], {"count": "screens"}], [t["stat_objects"], {"count": "objects"}],
                 [t["stat_tasks"], {"count": "tasks"}], [t["stat_serious"], {"count": "findings_serious"}]]
        out = {"entities": entities, "badges": self.badges(sev_values, sev_default, classes, types, bands),
               "stats": stats, "blocks": blocks}
        if self.prev:
            out = {"since": self.prev["diff"]["since"], **out}
        (self.data / "blocks.json").write_text(json.dumps(out, ensure_ascii=False, indent=1))
        return out


def main(argv):
    if len(argv) != 3 or argv[1] in ("-h", "--help"):
        sys.exit(__doc__)
    data, media = Path(argv[1]), Path(argv[2])
    if not data.is_dir() or not media.is_dir():
        sys.exit(f"compose: {data} and {media} must be directories")
    out = Compose(data, media).run()
    g = out["blocks"]["screens_gallery"]["items"]
    print(f"compose: {len(out['entities'])} entities, {len(out['blocks'])} blocks ({', '.join(out['blocks'])}), "
          f"{len(g)} gallery items, {sum(len(i.get('notes', [])) for i in g)} notes → {data / 'blocks.json'}")


if __name__ == "__main__":
    main(sys.argv)
