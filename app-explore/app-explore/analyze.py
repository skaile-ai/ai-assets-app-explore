#!/usr/bin/env python3
"""Turn an app-explore run's perceptions into findings and scores.

    python3 analyze.py <stem>.data [--since <prev stem>.data]

Reads graph.json, screens/, perceive.json, model.json, synonyms.json, scent.json, walks/*.json, critique/*.json,
saliency.json (feature `saliency`),
leaks.jsonl and run.json from the data dir (each optional except graph.json); every question, rule, gate, threshold and
clarity weight comes from rubric.json beside this file. Writes findings.json, scores.json, needs_check.json,
screens.json, objects.json and tasks.json into the data dir. Models perceive, the rules decide: an answer outside the
confidence gate never becomes a finding, it is listed in needs_check.json.

With `--since` (a previous run's data dir, analysed before) it also writes diff.json and gives every finding a
`status` (open: the same rule on the matching previous screen, or for a walk the same task, else new). A previous
finding with no current match is `fixed` when this run looked again (its screen matched, or its task was walked),
else `unverified`. Screens match by state key, else by route + kind + heading; a matched screen is `changed` past the
rubric.json `since` thresholds (dHash bits, clarity delta, interactive-label Jaccard).
"""
import json
import math
import re
import sys
from collections import deque
from pathlib import Path
from urllib.parse import urlsplit

RUBRIC = Path(__file__).with_name("rubric.json")


def load(path, default=None):
    try:
        return json.loads(Path(path).read_text())
    except FileNotFoundError:
        return default


def jsonl(path):
    try:
        return [json.loads(line) for line in Path(path).read_text().splitlines() if line.strip()]
    except FileNotFoundError:
        return []


def norm(s):
    return " ".join(str(s or "").split()).lower()


def hamming(a, b):
    """Bits that differ between two hex dHashes; None when either is missing or malformed."""
    try:
        return bin(int(a, 16) ^ int(b, 16)).count("1")
    except (TypeError, ValueError):
        return None


def jaccard(a, b):
    a, b = set(a), set(b)
    return 1.0 if not a and not b else len(a & b) / len(a | b)


def labels_of(screen):
    return {norm(m.get("label")) for m in (screen or {}).get("marks", []) if norm(m.get("label"))}


def route_re(route):
    """Regex for a crawl route (`:id` stands for one path segment)."""
    return re.compile("^" + "/".join("[^/#]+" if s == ":id" else re.escape(s) for s in str(route or "").split("/")) + "$")


def same_word(a, b):
    """Same word up to case and a plural ending: not a second name."""
    x, y = sorted((norm(a), norm(b)), key=len)
    return x == y or (y.startswith(x) and y[len(x):] in ("s", "es", "en", "n", "e"))


def distinct_labels(obj):
    labels = []
    for name in [obj.get("name"), *obj.get("aliases", [])]:
        if name and not any(same_word(name, seen) for seen in labels):
            labels.append(name)
    return labels


def bfs(edges, start):
    """Click distance from `start` to every reachable state."""
    nxt = {}
    for e in edges:
        nxt.setdefault(e["from"], []).append(e["to"])
    dist, q = {start: 0}, deque([start])
    while q:
        n = q.popleft()
        for m in nxt.get(n, []):
            if m not in dist:
                dist[m] = dist[n] + 1
                q.append(m)
    return dist


# ---------------------------------------------------------------- confidence gate


def gated(answer, qtype, gate):
    """(decided, value, leaning, confidence) of one judge answer under the gate.

    bool: true at P >= bool_true, false at P <= bool_false; choice: its top label when that probability >= choice;
    score: always decided, value = the probability-weighted level.
    """
    if qtype == "bool":
        p = answer["bool"]
        if p >= gate["bool_true"]:
            return True, True, True, p
        if p <= gate["bool_false"]:
            return True, False, False, 1 - p
        return False, None, p >= 0.5, max(p, 1 - p)
    if qtype == "choice":
        c = answer["choice"]
        p = answer.get("probabilities", {}).get(c, answer.get("confidence", 0))
        return (p >= gate["choice"]), (c if p >= gate["choice"] else None), c, p
    return True, answer["score"], answer["score"], answer.get("confidence")


def holds(cond, value):
    if "is" in cond:
        return value == cond["is"]
    if "in" in cond:
        return value in cond["in"]
    if "lt" in cond:
        return value is not None and value < cond["lt"]
    if "gt" in cond:
        return value is not None and value > cond["gt"]
    raise ValueError(f"rubric: condition without is/in/lt/gt: {cond}")


# ---------------------------------------------------------------- analysis


def seq_of(step):
    """A step's SEQ rating (1-7), None when missing or out of range."""
    v = step.get("seq")
    return v if isinstance(v, int) and not isinstance(v, bool) and 1 <= v <= 7 else None


def sus_score(items):
    """SUS 0-100 from the 10 answers (1-5, odd items positive, even negative); None unless all 10 are valid."""
    if not (isinstance(items, list) and len(items) == 10
            and all(isinstance(x, int) and not isinstance(x, bool) and 1 <= x <= 5 for x in items)):
        return None
    return 2.5 * sum(x - 1 if i % 2 == 0 else 5 - x for i, x in enumerate(items))


def wilson(k, n, z):
    """Wilson score interval (lo, hi) of k successes in n trials, as fractions rounded to 3 places."""
    p, d = k / n, 1 + z * z / n
    mid, half = (p + z * z / (2 * n)) / d, z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / d
    return round(max(0.0, mid - half), 3), round(min(1.0, mid + half), 3)


def median(xs):
    xs = sorted(xs)
    if not xs:
        return None
    m = len(xs) // 2
    return xs[m] if len(xs) % 2 else (xs[m - 1] + xs[m]) / 2


class Run:
    def __init__(self, data):
        self.data = Path(data)
        self.rubric = load(RUBRIC)
        self.gate = self.rubric["gate"]
        self.questions = self.rubric["questions"]
        self.rules = self.rubric["rules"]
        self.run = load(self.data / "run.json", {})
        self.features = {**self.rubric.get("features", {}), **(self.run.get("features") or {})}
        self.graph = load(self.data / "graph.json")
        if self.graph is None:
            sys.exit(f"analyze: {self.data / 'graph.json'} not found")
        self.states = {s["id"]: s for s in self.graph["states"]}
        self.order = [s["id"] for s in self.graph["states"]]
        self.entry = self.order[0] if self.order else None
        self.screens = {i: load(self.data / "screens" / f"{i}.json", {}) for i in self.order}
        self.perceive = load(self.data / "perceive.json", {})
        self.model = load(self.data / "model.json", {"personas": [], "objects": [], "tasks": []})
        self.scent = load(self.data / "scent.json", {})
        # walks per task: the base walk (walks/<task>.json, agent or kernel fallback) first, then with feature
        # personas > 1 its persona variants (walks/<task>-<variant>.json, `variant` set); self.walks = the base walks
        self.fanout = int(self.features.get("personas") or 1) > 1
        base, variants = {}, {}
        for p in sorted((self.data / "walks").glob("*.json")):
            w = load(p)
            tid = w.get("task") or p.stem
            if not w.get("variant"):
                base[tid] = w
            elif self.fanout:
                variants.setdefault(tid, []).append(w)
        self.walk_sets = {tid: [w] + variants.get(tid, []) for tid, w in base.items()}
        self.walk_sets.update((tid, ws) for tid, ws in variants.items() if tid not in base)
        self.walks = {tid: ws[0] for tid, ws in self.walk_sets.items()}
        self.critique = [c for p in sorted((self.data / "critique").glob("*.json")) for c in load(p, [])]
        self.leaks = jsonl(self.data / "leaks.jsonl")
        self.synonyms = load(self.data / "synonyms.json", [])
        self.depth = bfs(self.graph["edges"], self.entry) if self.entry else {}
        self.findings = {}
        self.needs = []

    def rules_of(self, source):
        return [r for r in self.rules if r["source"] == source]

    def rule(self, source):
        rules = self.rules_of(source)
        return rules[0] if rules else None

    def key8(self, state):
        return (self.states.get(state, {}).get("key") or state)[:8]

    def pins(self, state, marks, box=None):
        boxes = {m["n"]: m["box"] for m in self.screens.get(state, {}).get("marks", [])}
        pins = [{"x": round(b["x"] + b["w"] / 2, 1), "y": round(b["y"] + b["h"] / 2, 1), "n": n}
                for n in marks if (b := boxes.get(n))]
        if not pins and box:  # a critic finding anchored by its box only (feature `examples`)
            pins = [{"x": round(box["x"] + box["w"] / 2, 1), "y": round(box["y"] + box["h"] / 2, 1)}]
        return pins or [{"x": 4, "y": 4}]

    def add(self, rule, state, source, text, marks=(), confidence=1.0, sev=None, key=None, **extra):
        """One finding per (rule, state, key); repeats merge: marks union, max severity, texts joined."""
        fid = f"{rule['id'] if isinstance(rule, dict) else rule}@{self.key8(state)}" + (f"-{key}" if key else "")
        sev = rule["sev"] if sev is None else sev
        rid = rule["id"] if isinstance(rule, dict) else rule
        marks = [m for m in marks if m is not None]
        f = self.findings.get(fid)
        if f is None:
            self.findings[fid] = {"id": fid, "state": state, "source": source, "rule": rid, "sev": sev, "text": text,
                                  "marks": list(dict.fromkeys(marks)), "confidence": round(confidence, 2), **extra}
            return
        if text not in f["text"]:
            f["text"] += "; " + text
        f["marks"] = list(dict.fromkeys(f["marks"] + marks))
        f["sev"] = max(f["sev"], sev)
        f["confidence"] = max(f["confidence"], round(confidence, 2))
        for k, v in extra.items():
            if isinstance(v, list):
                f[k] = list(dict.fromkeys(f.get(k, []) + v))
            else:
                f.setdefault(k, v)

    def state_depth(self, sid):
        return self.depth.get(sid, self.states[sid].get("depth"))

    # rubric: judge answers per screen
    def rubric_findings(self):
        rules = self.rules_of("rubric")
        for sid in self.order:
            answers = (self.perceive.get(sid) or {}).get("answers")
            if not answers:
                self.needs.append({"state": sid, "source": "rubric", "question": "*", "answer": None, "leaning": None,
                                   "rules": [], "text": "Screen not judged: "
                                   + str((self.perceive.get(sid) or {}).get("judge_error", "no perception"))})
                continue
            g = {q: gated(a, self.questions[q]["type"], self.gate) for q, a in answers.items() if q in self.questions}
            for rule in rules:
                if rule.get("min_depth") and (self.state_depth(sid) or 0) < rule["min_depth"]:
                    continue
                conds = [rule] + ([rule["and"]] if "and" in rule else [])
                if any(c["q"] not in g for c in conds):
                    continue
                if all(g[c["q"]][0] for c in conds) and all(holds(c, g[c["q"]][1]) for c in conds):
                    conf = min((g[c["q"]][3] for c in conds if g[c["q"]][3] is not None), default=1.0)
                    self.add(rule, sid, "rubric", rule["text"], confidence=conf)
            for q, (decided, _, leaning, conf) in g.items():
                if decided:
                    continue
                would = []
                for rule in rules:
                    conds = [rule] + ([rule["and"]] if "and" in rule else [])
                    if q not in [c["q"] for c in conds] or any(c["q"] not in g for c in conds):
                        continue
                    if rule.get("min_depth") and (self.state_depth(sid) or 0) < rule["min_depth"]:
                        continue
                    if all(holds(c, g[c["q"]][2]) for c in conds):
                        would.append(rule["id"])
                self.needs.append({"state": sid, "source": "rubric", "question": q, "answer": answers[q],
                                   "leaning": leaning, "rules": would,
                                   "text": f"{self.questions[q]['instructions']} Leaning: {leaning} "
                                           f"(p {round(conf, 2)}), outside the confidence gate."})

    # geometry: DOM measurements from the crawl
    def geometry_findings(self):
        for rule in self.rules_of("geometry"):
            for sid in self.order:
                raw = self.screens[sid].get("geometry", {}).get(rule["field"], [])
                marks = [n for item in raw for n in (item if isinstance(item, list) else [item])]
                if marks:
                    self.add(rule, sid, "geometry", rule["text"], marks)

    # saliency (feature `saliency`): the primary action outside the predicted first look (saliency.json, saliency/run.py)
    def saliency_findings(self):
        if not self.features.get("saliency"):
            return
        sal = load(self.data / "saliency.json", {})
        for rule in self.rules_of("saliency"):
            for sid in self.order:
                s = sal.get(sid) or {}
                pm, rank, n, top = s.get("primary_mark"), s.get("primary_rank"), s.get("marks") or 0, s.get("top_marks")
                if pm is None or not rank or not top:
                    continue
                share, best = s.get("primary_share") or 0, top[0]
                low = rank > max(1, math.ceil(rule["top_frac"] * n))
                beaten = best["mark"] != pm and best["share"] > rule["max_ratio"] * share
                if not (low or beaten):
                    continue
                labels = {m["n"]: m.get("label", "") for m in self.screens.get(sid, {}).get("marks", [])}
                which = "" if s.get("primary_source") == "extract" else " (none flagged primary; the first action)"
                text = (f'{rule["text"]} mark {pm} "{labels.get(pm, "")}"{which} ranks {rank} of {n} marks by '
                        f'attention per pixel ({share}× the page average); mark {best["mark"]} '
                        f'"{labels.get(best["mark"], "")}" gets {best["share"]}×.')
                self.add(rule, sid, "saliency", text, [pm])

    def object_labels(self):
        """{object id: distinct labels} after the judge's synonym checks (synonyms.json, written by pipeline.mjs): an
        alias judged a different thing is dropped, a screen label judged the same joins, and two objects judged one
        thing share their labels (the first in model order carries the finding). Undecided pairs go to needs_check."""
        objs = {o["id"]: o for o in self.model["objects"]}
        labels = {i: distinct_labels(o) for i, o in objs.items()}
        root = {i: i for i in objs}
        order = list(objs)

        def find(i):
            while root[i] != i:
                i = root[i]
            return i

        for y in self.synonyms:
            oid = y.get("object")
            if not y.get("answer") or oid not in objs:
                continue
            decided, same, leaning, conf = gated(y["answer"], "bool", self.gate)
            if not decided:
                homes = objs[oid].get("homes") or [self.entry]
                self.needs.append({"state": homes[0], "source": "naming", "question": "synonym", "answer": y,
                                   "leaning": leaning, "rules": [r["id"] for r in self.rules_of("naming")],
                                   "text": f"\"{y['a']}\" and \"{y['b']}\" the same thing? Leaning: {leaning} "
                                           f"(p {round(conf, 2)}), outside the confidence gate."})
                continue
            if y.get("kind") == "alias" and not same:
                labels[oid] = [x for x in labels[oid] if not same_word(x, y["b"])]
            elif y.get("kind") == "label" and same and not any(same_word(x, y["b"]) for x in labels[oid]):
                labels[oid].append(y["b"])
            elif y.get("kind") == "objects" and same and y.get("other") in objs:
                a, b = sorted((find(oid), find(y["other"])), key=order.index)
                root[b] = a
        groups = {}
        for i in order:
            groups.setdefault(find(i), []).append(i)
        out = {}
        for members in groups.values():
            merged = []
            for i in members:
                merged += [x for x in labels[i] if not any(same_word(x, m) for m in merged)]
            for i in members:
                out[i] = merged
        self.groups = groups
        return out

    # naming: an object (or objects the judge confirmed as one) with several labels
    def naming_findings(self):
        rule = self.rule("naming")
        if not rule:
            return
        objs = {o["id"]: o for o in self.model["objects"]}
        for first, members in self.groups.items():
            o = objs[first]
            labels = self.labels[first]
            if len(labels) >= rule["min_labels"] and o.get("homes"):
                names = ", ".join(f'"{x}"' for x in labels)
                self.add(rule, o["homes"][0], "naming", f"{rule['text']} {names}.", key=o["id"], object=o["id"],
                         **({"objects": members[1:]} if len(members) > 1 else {}))

    # depth: target screens far from the start
    def depth_findings(self):
        rule = self.rule("depth")
        if not rule:
            return
        for t in self.model["tasks"]:
            d = self.depth.get(t.get("target_state"))
            if d is not None and holds(rule, d):
                self.add(rule, t["target_state"], "depth", f"{rule['text']} \"{t['title']}\": {d} clicks.",
                         tasks=[t["id"]])

    def url_state(self, url, route=True):
        """State of a page URL: exact url, else a page with the same path, else (with `route`) a page whose crawl
        route matches; None."""
        if not url:
            return None
        for sid in self.order:
            if self.states[sid].get("url") == url:
                return sid
        parts = urlsplit(url)
        pages = [sid for sid in self.order if self.states[sid]["kind"] == "page"]
        for sid in pages:
            if urlsplit(self.states[sid].get("url", "")).path == parts.path:
                return sid
        if not route:
            return None
        path = parts.path
        if parts.fragment.startswith(("/", "!")):
            path += "#" + parts.fragment.lstrip("!").split("?")[0]
        for sid in pages:
            if route_re(self.states[sid].get("route")).match(path):
                return sid
        return None

    def walk_state(self, walk, task):
        """State where a walk ended: the state of its last URL (url or path), else the task's target, else the entry."""
        steps = walk.get("steps") or []
        url = steps[-1].get("url") if steps else None
        return self.url_state(url, route=False) or (task or {}).get("target_state") or self.entry

    def walker(self, walk):
        """Who walked: the persona name, for a variant walk with the variant's name from model.json."""
        names = {v.get("id"): v.get("name") for p in self.model["personas"] for v in p.get("variants") or []}
        v = walk.get("variant")
        return f'{walk.get("persona")} ({names.get(v) or v})' if v else str(walk.get("persona"))

    @staticmethod
    def struggled(walk, rule):
        """A successful walk with at least `min_wrong_turns` confused steps or an ease at or below `max_ease`."""
        wrong = sum(1 for s in walk.get("steps", []) if s.get("confused"))
        ease = (walk.get("survey") or {}).get("ease")
        return wrong >= rule["min_wrong_turns"] or (ease is not None and ease <= rule["max_ease"])

    # walk: persona task walks, per task on the success rate of its walks (feature personas: base walk + variants).
    # W-failed at a rate <= its max_rate; else W-struggle when at least min_share of the walks failed or struggled.
    # A task with one walk keeps the single-walk text; the finding sits where its first failing (struggling) walk ended.
    def walk_findings(self):
        tasks = {t["id"]: t for t in self.model["tasks"]}
        rules = self.rules_of("walk")
        fail = next((r for r in rules if not r["success"]), None)
        for tid, ws in self.walk_sets.items():
            t = tasks.get(tid, {})
            title = t.get("title", tid)
            if tid in tasks and not t.get("target_state"):
                title += " (target screen not found in this crawl)"
            n, k = len(ws), sum(1 for w in ws if w.get("success"))
            failed = fail is not None and k / n <= fail["max_rate"]
            for rule in rules:
                if not rule["success"]:
                    hit = [w for w in ws if not w.get("success")] if failed else []
                elif failed:
                    continue
                else:
                    hit = [w for w in ws if not w.get("success") or self.struggled(w, rule)]
                    if len(hit) / n < rule["min_share"]:
                        continue
                if not hit:
                    continue
                w = hit[0]
                wrong = sum(1 for s in w.get("steps", []) if s.get("confused"))
                ease = (w.get("survey") or {}).get("ease")
                thinks = [s.get("think") for s in w.get("steps", []) if s.get("think")]
                extra = {}
                if n == 1:
                    quote = f' Last thought: "{thinks[-1]}"' if thinks else ""
                    turns = f"{wrong} wrong turn{'' if wrong == 1 else 's'}"
                    text = rule["text"] + f" \"{title}\": {w.get('clicks')} clicks, {turns}, ease {ease}.{quote}"
                else:
                    lo, hi = wilson(k, n, self.rubric["personas"]["wilson_z"])
                    clicks = median([x["clicks"] for x in ws if isinstance(x.get("clicks"), int)])
                    quote = f' Last thought of {self.walker(w)}: "{thinks[-1]}"' if thinks else ""
                    text = (f'{rule["rate_text"]} "{title}": {k} of {n} succeeded (95 % CI {round(lo * 100)}-'
                            f'{round(hi * 100)} %), median clicks {"—" if clicks is None else f"{clicks:g}"}; {"failed" if not rule["success"] else "failed or struggled"}: '
                            f'{", ".join(self.walker(x) for x in hit)}.{quote}')
                    extra = {"rate": round(k / n, 3), "walks": n}
                # one finding per task: walks that end on the same screen (or off the graph) stay apart
                self.add(rule, self.walk_state(w, t), "walk", text, key=tid, task=tid, tasks=[tid], **extra)

    # scent: first click from the entry screen
    def scent_findings(self):
        rule = self.rule("scent")
        if not rule:
            return
        tasks = {t["id"]: t for t in self.model["tasks"]}
        for tid, s in self.scent.items():
            if self.features.get("scent_path") and "steps" in s:
                continue  # path_scent_findings judges every path step, the entry included
            if s.get("correct") is None or s["correct"] != rule["correct"]:
                continue
            if (s.get("p") or 0) < self.gate["choice"]:
                self.needs.append({"state": s["entry"], "source": "scent", "question": "first_click", "answer": s,
                                   "leaning": True, "rules": [rule["id"]],
                                   "text": f"task {tid}: predicted mark {s['predicted_mark']} at p={s.get('p')}, outside the gate"})
                continue
            labels = {m["n"]: m["label"] for m in self.screens.get(s["entry"], {}).get("marks", [])}
            want = (f"mark {s['shortest_first_mark']} \"{labels.get(s['shortest_first_mark'], '')}\""
                    if s.get("shortest_first_mark") is not None
                    else " / ".join(f'"{x}"' for x in s.get("first_labels", [])) + " (not visible on the start screen)")
            text = (f"{rule['text']} \"{tasks.get(tid, {}).get('title', tid)}\": would click mark "
                    f"{s['predicted_mark']} \"{labels.get(s['predicted_mark'], '')}\", the path starts at {want}.")
            self.add(rule, s["entry"], "scent", text, [s["predicted_mark"]], s.get("p") or 0, tasks=[tid])
        self.path_scent_findings(rule, tasks)

    # scent along the path (feature scent_path): one S-scent or S-premature per wrong step, gated like the entry
    def path_scent_findings(self, rule, tasks):
        if not self.features.get("scent_path"):
            return
        early = next((r for r in self.rules_of("scent") if r.get("premature")), None)
        for tid, s in self.scent.items():
            steps = s.get("steps") or []
            title = tasks.get(tid, {}).get("title", tid)
            for st in steps:
                if st.get("correct") is None or st["correct"] != rule["correct"]:
                    continue
                r = early if st.get("premature") and early else rule
                where = f"step {st['step'] + 1} of {len(steps)}"
                if (st.get("p") or 0) < self.gate["choice"]:
                    self.needs.append({"state": st["state"], "source": "scent", "question": "path_pick", "answer": st,
                                       "leaning": True, "rules": [r["id"]],
                                       "text": f"task {tid} {where}: predicted mark {st.get('predicted')} "
                                               f"at p={st.get('p')}, outside the gate"})
                    continue
                labels = {m["n"]: m["label"] for m in self.screens.get(st["state"], {}).get("marks", [])}
                mark = lambda n: f"mark {n} \"{labels.get(n, '')}\""
                pick = (f"would click {mark(st['predicted'])} (group {st['chunk']} of {st['chunks']} in reading order)"
                        if st.get("predicted") is not None else "would click nothing here")
                want = (" / ".join(mark(n) for n in st["expected"]) + (f" (group {st['expected_chunk']})"
                                                                       if st.get("expected_chunk") else "")
                        if st.get("expected") else "a control without a mark on this screen")
                lead = r.get("path_text", r["text"]) if st["step"] else r["text"]
                text = f"{lead} \"{title}\", {where}: {pick}; the path continues at {want}."
                self.add(r, st["state"], "scent", text, [st.get("predicted")], st.get("p") or 0, tasks=[tid],
                         steps=[f"{tid}:{st['step'] + 1}"])

    # leak: writes that reached the server in readonly mode
    def leak_findings(self):
        for rule in self.rules_of("leak"):
            if self.run.get("mode", "readonly") != rule["mode"]:
                continue
            tasks = {t["id"]: t for t in self.model["tasks"]}
            for x in self.leaks:
                sid = x.get("state") if x.get("state") in self.states else self.url_state(x.get("page")) or self.entry
                task = x.get("task")
                walk = f" during the walk of task {task} \"{tasks.get(task, {}).get('title', task)}\"" if task else ""
                self.add(rule, sid, "leak", f"{rule['text']} {x.get('method')} {x.get('url')} ({x.get('status')}){walk}.",
                         **({"tasks": [task]} if task else {}))

    # critic: deep critique by the slow model
    def critic_findings(self):
        anchored = self.features.get("examples")
        for c in self.critique:
            if c.get("state") not in self.states:
                continue
            conf = c.get("confidence", 0)
            extra = self.critic_anchor(c) if anchored else {}
            if anchored and not extra.get("box") and not self.known_marks(c["state"], c.get("marks") or []):
                self.needs.append({"state": c["state"], "source": "critic", "question": c["rule"], "answer": c,
                                   "leaning": True, "rules": [c["rule"]],
                                   "text": f"{c['text']} (no box and no marks: not placed on the screen)"})
            elif conf >= self.gate["critic"]:
                self.add(c["rule"], c["state"], "critic", c["text"], c.get("marks", []), conf, sev=c["sev"], **extra)
            else:
                self.needs.append({"state": c["state"], "source": "critic", "question": c["rule"], "answer": c,
                                   "leaning": True, "rules": [c["rule"]],
                                   "text": f"{c['text']} (confidence {conf}, outside the gate)"})

    def known_marks(self, state, marks):
        """The marks of `marks` that exist in the state's screens/<id>.json."""
        have = {m["n"] for m in self.screens.get(state, {}).get("marks", [])}
        return [n for n in marks if n in have]

    @staticmethod
    def critic_anchor(c):
        """Feature `examples`: the finding's `box` ({x, y, w, h} in viewport percent, clipped to the screen; dropped
        when malformed or empty) and `example_ids` (the bank examples it follows)."""
        out, b = {}, c.get("box")
        if isinstance(b, dict) and all(isinstance(b.get(k), (int, float)) for k in "xywh"):
            x, y = min(max(b["x"], 0), 100), min(max(b["y"], 0), 100)
            w, h = min(b["w"], 100 - x), min(b["h"], 100 - y)
            if w > 0 and h > 0:
                out["box"] = {"x": round(x, 1), "y": round(y, 1), "w": round(w, 1), "h": round(h, 1)}
        ids = c.get("example_ids")
        out["example_ids"] = [str(i) for i in ids] if isinstance(ids, list) else []
        return out

    # mental: where the app breaks a simulated first-time user's mental model (feature mental_model)
    def mental_findings(self):
        """M-expectation per violation of mentalmodel.json (pipeline.mjs `mentalModel`), on the state the click led to
        (a walk step off the crawled graph: the task's target, else the entry; the text names the URL), one finding
        per state and violation kind. A naming violation whose two names the naming rule already holds as one object's
        labels, or that the synonym check judged two different things, is that check's call and adds nothing. Crawl
        matches outside the gate go to needs_check."""
        if not self.features.get("mental_model"):
            return
        mm = load(self.data / "mentalmodel.json")
        rules = {r["kind"]: r for r in self.rules_of("mental")}
        if not mm or not rules:
            return
        tasks = {t["id"]: t for t in self.model["tasks"]}
        heading = lambda sid: (self.states.get(sid) or {}).get("heading") or (self.states.get(sid) or {}).get("title") or sid
        for t in mm.get("timeline", []):
            if t.get("source") == "crawl" and t.get("step") and t.get("matches") is None and t.get("p") is not None:
                pred = t.get("predicted") or {}
                self.needs.append({"state": t["state"], "source": "mental", "question": "matches", "answer": {"bool": t["p"]},
                                   "leaning": t["p"] >= 0.5, "rules": [rules[next(iter(rules))]["id"]],
                                   "text": f"Clicking \"{t.get('label')}\" on \"{heading(t.get('from'))}\": does it show what a "
                                           f"first-time user predicted ({pred.get('kind')} \"{pred.get('heading')}\")? "
                                           f"Leaning: {t['p'] >= 0.5} (p {t['p']}), outside the confidence gate."})
        for v in mm.get("violations", []):
            rule = rules.get(v.get("kind"))
            if not rule or (v["kind"] == "naming" and self.mental_naming_known(v)):
                continue
            task = v.get("task")
            sid = v.get("state") if v.get("state") in self.states else None
            off = "" if sid else f" (at {v.get('url')}, outside the crawl)" if v.get("url") else ""
            sid = sid or (tasks.get(task, {}).get("target_state") if tasks.get(task, {}).get("target_state") in self.states
                          else self.entry)
            names = " / ".join(f'"{x}"' for x in v.get("names") or [])
            where = (f" Task \"{tasks.get(task, {}).get('title', task)}\", step {v.get('walk_step', 0) + 1}:" if v.get("source") == "walk"
                     else f" On \"{heading(v.get('from'))}\":")
            text = (f"{rule['text']}{where} clicked \"{v.get('label')}\"{off}{', names ' + names if names else ''}; "
                    f"expected {v.get('expected')}; got {v.get('observed')}.")
            self.add(rule, sid, "mental", text, confidence=v.get("p") or 1.0, key=v["kind"], violations=[v["id"]],
                     **({"tasks": [task]} if task in tasks else {}))

    def mental_naming_known(self, v):
        """The naming rule already holds both names as one object's labels, or the synonym check judged the pair two
        different things (same-object-different-name only)."""
        a, b = (v.get("names") or [None, None])[:2]
        if not a or not b:
            return True
        if any(any(same_word(a, x) for x in labels) and any(same_word(b, x) for x in labels) for labels in self.labels.values()):
            return True
        if v.get("naming") != "same-object-different-name":
            return False
        for y in self.synonyms:
            pair = (y.get("a"), y.get("b"))
            if y.get("answer") and ((same_word(a, pair[0]) and same_word(b, pair[1])) or (same_word(a, pair[1]) and same_word(b, pair[0]))):
                decided, same, _, _ = gated(y["answer"], "bool", self.gate)
                if decided and not same:
                    return True
        return False

    # ---------------------------------------------------------------- scores

    def clarity(self, sid):
        answers = (self.perceive.get(sid) or {}).get("answers")
        if not answers:
            return None
        parts = []
        for q, spec in self.rubric["clarity"].items():
            a = answers.get(q)
            if a is None:
                continue
            qtype = self.questions[q]["type"]
            if q == "location" and "depth0" in spec and self.state_depth(sid) == 0:
                parts.append(spec["depth0"])
            elif qtype == "score":
                parts.append(max(0.0, min(1.0, a["score"] / spec["score_max"])))
            else:
                decided, value, _, _ = gated(a, qtype, self.gate)
                vals = spec["values"]
                if qtype == "bool":
                    # undecided answers count by their probability, decided ones by their gated value
                    parts.append(vals[str(value).lower()] if decided
                                 else a["bool"] * vals["true"] + (1 - a["bool"]) * vals["false"])
                else:
                    parts.append(vals[value] if decided
                                 else sum(p * vals.get(label, 0) for label, p in a.get("probabilities", {}).items()))
        return round(100 * sum(parts) / len(parts)) if parts else None

    def write(self, since=None):
        self.labels = self.object_labels()
        for step in (self.rubric_findings, self.geometry_findings, self.saliency_findings, self.naming_findings,
                     self.depth_findings, self.walk_findings, self.friction_findings, self.scent_findings,
                     self.leak_findings, self.critic_findings, self.mental_findings):
            step()
        rank = {sid: i for i, sid in enumerate(self.order)}
        findings = sorted(self.findings.values(), key=lambda f: (-f["sev"], rank.get(f["state"], 0), f["rule"]))
        for f in findings:
            f["pins"] = self.pins(f["state"], f["marks"], f.get("box"))

        clarity = {sid: self.clarity(sid) for sid in self.order}
        known = [c for c in clarity.values() if c is not None]
        tasks = self.task_rows()
        findability = self.findability(tasks)
        objs = self.model["objects"]
        rule = self.rule("naming")
        multi = sum(1 for o in objs if rule and len(self.labels[o["id"]]) >= rule["min_labels"])
        scores = {"screens": clarity, "app": {
            "clarity": round(sum(known) / len(known)) if known else None,
            "findability": findability,
            "naming": round(1 - multi / len(objs), 3) if objs else None,
            **self.sus_scores(tasks),
        }}

        by_state = {}
        for f in findings:
            by_state.setdefault(f["state"], []).append(f["sev"])
        screens = []
        for sid in self.order:
            s, p = self.states[sid], self.perceive.get(sid) or {}
            st = (p.get("answers") or {}).get("screen_type")
            screens.append({
                "id": sid, "key": s.get("key"), "url": s.get("url"), "route": s.get("route"), "kind": s.get("kind"),
                "title": s.get("title"), "heading": s.get("heading"), "depth": self.depth.get(sid),
                "parent": s.get("parent"), "shot": s.get("shot"), "som": s.get("som"),
                "mobile_shot": s.get("mobile_shot"), "instances": s.get("instances"),
                "purpose": (p.get("extract") or {}).get("purpose"),
                "screen_type": gated(st, "choice", self.gate)[1] if st else None,
                "clarity": clarity[sid], "findings": len(by_state.get(sid, [])),
                "max_sev": max(by_state[sid]) if sid in by_state else None,
            })
        objects = [{
            "id": o["id"], "name": o["name"], "class": o.get("class"), "aliases": o.get("aliases", []),
            "labels": len(self.labels[o["id"]]), "attributes": o.get("attributes", []),
            "relationships": o.get("relationships", []), "ctas": o.get("ctas", []), "homes": o.get("homes", []),
            "representations": o.get("representations", []),
            "shown_as": list(dict.fromkeys(r["as"] for r in o.get("representations", []))),
            "findings": sum(1 for f in findings if f.get("object") == o["id"]),
        } for o in objs]

        out = {"findings.json": findings, "scores.json": scores, "needs_check.json": self.needs,
               "screens.json": screens, "objects.json": objects, "tasks.json": tasks}
        diff = self.diff(Path(since), clarity, findings, objects, tasks) if since else None
        if diff:
            out["diff.json"] = diff
        else:
            (self.data / "diff.json").unlink(missing_ok=True)
        for name, value in out.items():
            (self.data / name).write_text(json.dumps(value, indent=2, ensure_ascii=False))
        return findings, scores, diff

    # ---------------------------------------------------------------- since: diff against a previous run

    def match(self, prev_states):
        """{current state id: previous state id}, one to one: by state key, else by route + kind + heading."""
        match, used = {}, set()
        for sig in (lambda s: s.get("key"), lambda s: (s.get("route"), s.get("kind"), norm(s.get("heading")))):
            index = {}
            for p in prev_states:
                if p["id"] not in used:
                    index.setdefault(sig(p), []).append(p["id"])
            for sid in self.order:
                if sid in match:
                    continue
                cands = [p for p in index.get(sig(self.states[sid]), []) if p not in used]
                if cands:
                    match[sid] = cands[0]
                    used.add(cands[0])
        return match

    def diff(self, prev, clarity, findings, objects, tasks):
        pgraph = load(prev / "graph.json")
        if not prev.is_dir() or pgraph is None:
            sys.exit(f"since: {prev} has no .data/ dir")
        pstates = pgraph["states"]
        pclarity = (load(prev / "scores.json", {}) or {}).get("screens", {})
        pfindings = load(prev / "findings.json", [])
        match = self.match(pstates)
        matched = set(match.values())

        changed = []
        for sid, pid in match.items():
            p = next(s for s in pstates if s["id"] == pid)
            dist = hamming(self.states[sid].get("hash"), p.get("hash"))
            c, pc = clarity.get(sid), pclarity.get(pid)
            delta = c - pc if c is not None and pc is not None else None
            jac = round(jaccard(labels_of(self.screens[sid]), labels_of(load(prev / "screens" / f"{pid}.json", {}))), 3)
            ch = self.rubric["since"]
            if ((dist is not None and dist > ch["hash_bits"]) or (delta is not None and abs(delta) >= ch["clarity_delta"])
                    or jac < ch["jaccard"]):
                changed.append({"id": sid, "prev": pid, "dist": dist, "clarity_delta": delta, "jaccard": jac})

        # findings: the same rule (and object, for naming) on the matching previous screen is the same finding; a walk
        # finding is the same finding when it is about the same task, wherever the walk ended
        def walk_task(f):
            return (f.get("task") or (f.get("tasks") or [None])[0]) if f.get("source") == "walk" else None

        def ident(f, state):
            task = walk_task(f)
            return (f["rule"], task) if task else (f["rule"], state, f.get("object"))

        now = {ident(f, match.get(f["state"])) for f in findings}
        before = {ident(f, f["state"]) for f in pfindings}
        for f in findings:
            f["status"] = "open" if ident(f, match.get(f["state"])) in before else "new"
        # a previous finding no longer firing is `fixed` only where this run looked again: its screen was matched, or
        # (walk findings) its task was walked again; else `unverified` (this run did not reach that screen)
        rechecked = lambda f: walk_task(f) in self.walks if walk_task(f) else f["state"] in matched
        gone = [f for f in pfindings if ident(f, f["state"]) not in now]
        fixed = [f["id"] for f in gone if rechecked(f)]
        unverified = [f["id"] for f in gone if not rechecked(f)]

        pobjects = {o["id"]: o for o in load(prev / "objects.json", [])}
        cobjects = {o["id"]: o for o in objects}
        brief = lambda t: {k: t.get(k) for k in ("title", "walked", "success", "clicks", "ease", "shortest")
                           + (("sus",) if self.features.get("seq") else ())
                           + (("walks", "rate", "rate_ci") + (("sus_mean",) if self.features.get("seq") else ())
                              if self.fanout else ())}
        ptasks = {t["id"]: t for t in load(prev / "tasks.json", [])}
        ctasks = {t["id"]: t for t in tasks}
        return {
            "since": prev.name[:-5] if prev.name.endswith(".data") else prev.name,
            "since_data": str(prev.resolve()),
            "match": match,
            "screens": {
                "new": [sid for sid in self.order if sid not in match],
                "removed": [p["id"] for p in pstates if p["id"] not in matched],
                "changed": changed,
            },
            "objects": {
                "new": [i for i in cobjects if i not in pobjects],
                "removed": [i for i in pobjects if i not in cobjects],
                "renamed": [{"id": i, "prev": pobjects[i].get("name"), "now": o.get("name")} for i, o in cobjects.items()
                            if i in pobjects and norm(pobjects[i].get("name")) != norm(o.get("name"))],
            },
            "tasks": {i: {"prev": brief(ptasks[i]) if i in ptasks else None, "now": brief(ctasks[i]) if i in ctasks else None}
                      for i in list(ctasks) + [i for i in ptasks if i not in ctasks]},
            "findings": {
                "fixed": fixed,
                "unverified": unverified,
                "open": [f["id"] for f in findings if f["status"] == "open"],
                "new": [f["id"] for f in findings if f["status"] == "new"],
            },
        }

    def task_rows(self):
        personas = {p["id"]: p for p in self.model["personas"]}
        rows = []
        for t in self.model["tasks"]:
            w = self.walks.get(t["id"])
            shortest = self.depth.get(t.get("target_state"))
            clicks = w.get("clicks") if w else None
            success = bool(w.get("success")) if w else None
            directness = self.directness(w, shortest) if w else None
            survey = (w or {}).get("survey") or {}
            rows.append({
                "id": t["id"], "title": t["title"], "persona": t["persona"],
                "persona_name": personas.get(t["persona"], {}).get("name"), "object": t.get("object"),
                "verb": t.get("verb"), "target_state": t.get("target_state"), "shortest": shortest,
                "scent_correct": (self.scent.get(t["id"]) or {}).get("correct"), "walked": w is not None,
                "success": success, "clicks": clicks, "directness": directness,
                "ease": survey.get("ease"), "confidence": survey.get("confidence"), **self.seq_cols(w),
                **self.fanout_cols(t["id"]),
            })
        return rows

    def fanout_cols(self, tid):
        """tasks.json columns of feature personas > 1, over the base walk and its variants: `walks` (n), `successes`,
        `rate` with its Wilson 95 % interval `rate_ci` [lo, hi], median and range of clicks and ease; with `seq` the
        mean and range of SUS. None of them when the feature is off."""
        if not self.fanout:
            return {}
        ws = self.walk_sets.get(tid) or []
        n, k = len(ws), sum(1 for w in ws if w.get("success"))
        num = lambda v: isinstance(v, (int, float)) and not isinstance(v, bool)
        clicks = [w["clicks"] for w in ws if num(w.get("clicks"))]
        ease = [e for w in ws if num(e := (w.get("survey") or {}).get("ease"))]
        span = lambda xs: [min(xs), max(xs)] if xs else None
        out = {"walks": n, "successes": k if n else None, "rate": round(k / n, 3) if n else None,
               "rate_ci": list(wilson(k, n, self.rubric["personas"]["wilson_z"])) if n else None,
               "clicks_median": median(clicks), "clicks_range": span(clicks), "ease_median": median(ease)}
        if self.features.get("seq"):
            sus = [x for w in ws if (x := sus_score((w.get("survey") or {}).get("sus"))) is not None]
            out.update(sus_mean=round(sum(sus) / len(sus), 1) if sus else None, sus_range=span(sus))
        return out

    # ---------------------------------------------------------------- seq: step difficulty and SUS (feature `seq`)

    def friction_findings(self):
        """W-friction on the state of every walk step rated SEQ <= max_seq or min_drop below the step before."""
        if not self.features.get("seq"):
            return
        tasks = {t["id"]: t for t in self.model["tasks"]}
        for rule in self.rules_of("seq"):
            for tid, w in ((tid, w) for tid, ws in self.walk_sets.items() for w in ws):
                t = tasks.get(tid, {})
                before = None
                for i, s in enumerate(w.get("steps") or [], 1):
                    v = seq_of(s)
                    if v is None:
                        continue
                    drop = before is not None and before - v >= rule["min_drop"]
                    if v <= rule["max_seq"] or drop:
                        what = f'{s.get("action")} "{s["label"]}"' if s.get("label") else s.get("action")
                        text = (f'{rule["text"]} "{t.get("title", tid)}"' + (f" ({self.walker(w)})" if w.get("variant") else "")
                                + f", step {i} ({what}): SEQ {v}/7"
                                + (f" after {before}" if drop else "")
                                + (f'. Thought: "{s["think"]}"' if s.get("think") else "."))
                        state = self.url_state(s.get("url")) or self.walk_state(w, t)
                        self.add(rule, state, "seq", text, key=tid, task=tid, tasks=[tid])
                    before = v

    def seq_cols(self, walk):
        """tasks.json columns of feature `seq`: SEQ per step and the walk's SUS; none when the feature is off."""
        if not self.features.get("seq"):
            return {}
        steps = (walk or {}).get("steps") or []
        return {"seq": [seq_of(s) for s in steps] if walk else None,
                "sus": sus_score(((walk or {}).get("survey") or {}).get("sus"))}

    def sus_scores(self, tasks):
        """scores.json app keys of feature `seq`: mean SUS over walks (with feature personas every walk of a task, its
        variants included) and per persona; none when the feature is off."""
        if not self.features.get("seq"):
            return {}
        mean = lambda xs: round(sum(xs) / len(xs), 1) if xs else None
        per = {}
        for t in tasks:
            for w in self.walk_sets.get(t["id"]) or []:
                x = sus_score((w.get("survey") or {}).get("sus"))
                if x is not None:
                    per.setdefault(t["persona"], []).append(x)
        return {"sus": mean([x for xs in per.values() for x in xs]), "sus_personas": {p: mean(xs) for p, xs in per.items()}}

    @staticmethod
    def directness(walk, shortest):
        """Shortest path / clicks of a successful walk, capped at 1 (1 when the target is the start); else None."""
        success, clicks = bool(walk.get("success")), walk.get("clicks")
        return (round(min(1.0, shortest / clicks), 3) if success and clicks and shortest is not None
                else (1.0 if success and shortest == 0 else None))

    def findability(self, tasks):
        """Mean success rate over walked tasks (one walk: 0 or 1; feature personas: k/n of its walks) × mean task
        directness (per task the mean over its successful walks); None before walks."""
        rates, direct = [], []
        for t in tasks:
            ws = self.walk_sets.get(t["id"])
            if not ws:
                continue
            ok = [w for w in ws if w.get("success")]
            rates.append(len(ok) / len(ws))
            d = [x for w in ok if (x := self.directness(w, t["shortest"])) is not None]
            if d:
                direct.append(sum(d) / len(d))
        return round(sum(rates) / len(rates) * (sum(direct) / len(direct) if direct else 0), 3) if rates else None


def main(argv):
    args, since = argv[1:], None
    if len(args) == 3 and args[1] == "--since":
        args, since = args[:1], args[2]
    if len(args) != 1 or args[0].startswith("-"):
        sys.exit("usage: python3 analyze.py <stem>.data [--since <prev stem>.data]")
    if since and not Path(since).is_dir():
        sys.exit(f"since: {since} has no .data/ dir")
    findings, scores, diff = Run(args[0]).write(since)
    sev = {}
    for f in findings:
        sev[f["sev"]] = sev.get(f["sev"], 0) + 1
    print(f"analyze: {len(findings)} findings "
          + " ".join(f"S{k}:{v}" for k, v in sorted(sev.items(), reverse=True))
          + f", app clarity {scores['app']['clarity']}, findability {scores['app']['findability']}, "
            f"naming {scores['app']['naming']}")
    if diff:
        s, f = diff["screens"], diff["findings"]
        print(f"since {diff['since']}: screens {len(s['new'])} new, {len(s['removed'])} removed, {len(s['changed'])} changed; "
              f"findings {len(f['new'])} new, {len(f['open'])} open, {len(f['fixed'])} fixed, "
              f"{len(f['unverified'])} unverified")


if __name__ == "__main__":
    main(sys.argv)
