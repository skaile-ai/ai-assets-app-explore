#!/usr/bin/env python3
"""Turn an app-explore run's perceptions into findings and scores.

    python3 analyze.py <stem>.data [--since <prev stem>.data]

Reads graph.json, screens/, perceive.json, model.json, scent.json, walks/*.json, critique/*.json, leaks.jsonl and
run.json from the data dir (each optional except graph.json); every question, rule, gate and clarity weight comes
from rubric.json beside this file. Writes findings.json, scores.json, needs_check.json, screens.json, objects.json
and tasks.json into the data dir. Models perceive, the rules decide: an answer outside the confidence gate never
becomes a finding, it is listed in needs_check.json.

With `--since` (a previous run's data dir, analysed before) it also writes diff.json and gives every finding a
`status` (open: the same rule on the matching previous screen, else new); previous findings with no current match
are `fixed`. Screens match by state key, else by route + kind + heading; a matched screen is `changed` when its
dHash differs by more than 10 bits, its clarity by 10 or more, or its interactive labels' Jaccard is under 0.8.
"""
import json
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


CHANGED = {"hash_bits": 10, "clarity_delta": 10, "jaccard": 0.8}  # plan step 7 thresholds


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


class Run:
    def __init__(self, data):
        self.data = Path(data)
        self.rubric = load(RUBRIC)
        self.gate = self.rubric["gate"]
        self.questions = self.rubric["questions"]
        self.rules = self.rubric["rules"]
        self.run = load(self.data / "run.json", {})
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
        self.walks = {}
        for p in sorted((self.data / "walks").glob("*.json")):
            w = load(p)
            self.walks[w.get("task") or p.stem] = w
        self.critique = [c for p in sorted((self.data / "critique").glob("*.json")) for c in load(p, [])]
        self.leaks = jsonl(self.data / "leaks.jsonl")
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

    def pins(self, state, marks):
        boxes = {m["n"]: m["box"] for m in self.screens.get(state, {}).get("marks", [])}
        pins = [{"x": round(b["x"] + b["w"] / 2, 1), "y": round(b["y"] + b["h"] / 2, 1), "n": n}
                for n in marks if (b := boxes.get(n))]
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

    # naming: an object with several labels
    def naming_findings(self):
        rule = self.rule("naming")
        if not rule:
            return
        for o in self.model["objects"]:
            labels = distinct_labels(o)
            if len(labels) >= rule["min_labels"] and o.get("homes"):
                names = ", ".join(f'"{x}"' for x in labels)
                self.add(rule, o["homes"][0], "naming", f"{rule['text']} {names}.", key=o["id"], object=o["id"])

    # depth: target screens far from the start
    def depth_findings(self):
        rule = self.rule("depth")
        if not rule:
            return
        for t in self.model["tasks"]:
            d = self.depth.get(t["target_state"])
            if d is not None and holds(rule, d):
                self.add(rule, t["target_state"], "depth", f"{rule['text']} \"{t['title']}\": {d} clicks.",
                         tasks=[t["id"]])

    def walk_state(self, walk, task):
        """State where a walk ended: exact url, else same path, else the task's target."""
        steps = walk.get("steps") or []
        url = steps[-1].get("url") if steps else None
        if url:
            for sid in self.order:
                if self.states[sid].get("url") == url:
                    return sid
            path = urlsplit(url).path
            for sid in self.order:
                if urlsplit(self.states[sid].get("url", "")).path == path and self.states[sid]["kind"] == "page":
                    return sid
        return (task or {}).get("target_state") or self.entry

    # walk: persona task walks
    def walk_findings(self):
        tasks = {t["id"]: t for t in self.model["tasks"]}
        for tid, w in self.walks.items():
            t = tasks.get(tid, {})
            title = t.get("title", tid)
            wrong = sum(1 for s in w.get("steps", []) if s.get("confused"))
            ease = (w.get("survey") or {}).get("ease")
            thinks = [s.get("think") for s in w.get("steps", []) if s.get("think")]
            quote = f' Last thought: "{thinks[-1]}"' if thinks else ""
            for rule in self.rules_of("walk"):
                if bool(w.get("success")) != rule["success"]:
                    continue
                if rule["success"] and not (wrong >= rule["min_wrong_turns"]
                                            or (ease is not None and ease <= rule["max_ease"])):
                    continue
                turns = f"{wrong} wrong turn{'' if wrong == 1 else 's'}"
                detail = f" \"{title}\": {w.get('clicks')} clicks, {turns}, ease {ease}.{quote}"
                self.add(rule, self.walk_state(w, t), "walk", rule["text"] + detail, tasks=[tid])

    # scent: first click from the entry screen
    def scent_findings(self):
        rule = self.rule("scent")
        if not rule:
            return
        tasks = {t["id"]: t for t in self.model["tasks"]}
        for tid, s in self.scent.items():
            if s.get("correct") is None or s["correct"] != rule["correct"]:
                continue
            labels = {m["n"]: m["label"] for m in self.screens.get(s["entry"], {}).get("marks", [])}
            want = (f"mark {s['shortest_first_mark']} \"{labels.get(s['shortest_first_mark'], '')}\""
                    if s.get("shortest_first_mark") is not None
                    else " / ".join(f'"{x}"' for x in s.get("first_labels", [])) + " (not visible on the start screen)")
            text = (f"{rule['text']} \"{tasks.get(tid, {}).get('title', tid)}\": would click mark "
                    f"{s['predicted_mark']} \"{labels.get(s['predicted_mark'], '')}\", the path starts at {want}.")
            self.add(rule, s["entry"], "scent", text, [s["predicted_mark"]], s.get("p") or 0, tasks=[tid])

    # leak: writes that reached the server in readonly mode
    def leak_findings(self):
        for rule in self.rules_of("leak"):
            if self.run.get("mode", "readonly") != rule["mode"]:
                continue
            for x in self.leaks:
                sid = x.get("state") if x.get("state") in self.states else self.entry
                self.add(rule, sid, "leak", f"{rule['text']} {x.get('method')} {x.get('url')} ({x.get('status')}).")

    # critic: deep critique by the slow model
    def critic_findings(self):
        for c in self.critique:
            if c.get("state") not in self.states:
                continue
            conf = c.get("confidence", 0)
            if conf >= self.gate["critic"]:
                self.add(c["rule"], c["state"], "critic", c["text"], c.get("marks", []), conf, sev=c["sev"])
            else:
                self.needs.append({"state": c["state"], "source": "critic", "question": c["rule"], "answer": c,
                                   "leaning": True, "rules": [c["rule"]],
                                   "text": f"{c['text']} (confidence {conf}, outside the gate)"})

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
        for step in (self.rubric_findings, self.geometry_findings, self.naming_findings, self.depth_findings,
                     self.walk_findings, self.scent_findings, self.leak_findings, self.critic_findings):
            step()
        rank = {sid: i for i, sid in enumerate(self.order)}
        findings = sorted(self.findings.values(), key=lambda f: (-f["sev"], rank.get(f["state"], 0), f["rule"]))
        for f in findings:
            f["pins"] = self.pins(f["state"], f["marks"])

        clarity = {sid: self.clarity(sid) for sid in self.order}
        known = [c for c in clarity.values() if c is not None]
        tasks = self.task_rows()
        walked = [t for t in tasks if t["walked"]]
        succ = [t for t in walked if t["success"]]
        direct = [t["directness"] for t in succ if t["directness"] is not None]
        findability = (round(len(succ) / len(walked) * (sum(direct) / len(direct) if direct else 0), 3)
                       if walked else None)
        objs = self.model["objects"]
        rule = self.rule("naming")
        multi = sum(1 for o in objs if rule and len(distinct_labels(o)) >= rule["min_labels"])
        scores = {"screens": clarity, "app": {
            "clarity": round(sum(known) / len(known)) if known else None,
            "findability": findability,
            "naming": round(1 - multi / len(objs), 3) if objs else None,
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
            "labels": len(distinct_labels(o)), "attributes": o.get("attributes", []),
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
            if ((dist is not None and dist > CHANGED["hash_bits"]) or (delta is not None and abs(delta) >= CHANGED["clarity_delta"])
                    or jac < CHANGED["jaccard"]):
                changed.append({"id": sid, "prev": pid, "dist": dist, "clarity_delta": delta, "jaccard": jac})

        # findings: the same rule (and object, for naming) on the matching previous screen is the same finding
        now = {(f["rule"], match.get(f["state"]), f.get("object")) for f in findings}
        before = {(f["rule"], f["state"], f.get("object")) for f in pfindings}
        for f in findings:
            f["status"] = "open" if (f["rule"], match.get(f["state"]), f.get("object")) in before else "new"
        fixed = [f["id"] for f in pfindings if (f["rule"], f["state"], f.get("object")) not in now]

        pobjects = {o["id"]: o for o in load(prev / "objects.json", [])}
        cobjects = {o["id"]: o for o in objects}
        brief = lambda t: {k: t.get(k) for k in ("title", "walked", "success", "clicks", "ease", "shortest")}
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
                "open": [f["id"] for f in findings if f["status"] == "open"],
                "new": [f["id"] for f in findings if f["status"] == "new"],
            },
        }

    def task_rows(self):
        personas = {p["id"]: p for p in self.model["personas"]}
        rows = []
        for t in self.model["tasks"]:
            w = self.walks.get(t["id"])
            shortest = self.depth.get(t["target_state"])
            clicks = w.get("clicks") if w else None
            success = bool(w.get("success")) if w else None
            directness = (round(min(1.0, shortest / clicks), 3) if success and clicks and shortest is not None
                          else (1.0 if success and shortest == 0 else None))
            survey = (w or {}).get("survey") or {}
            rows.append({
                "id": t["id"], "title": t["title"], "persona": t["persona"],
                "persona_name": personas.get(t["persona"], {}).get("name"), "object": t.get("object"),
                "verb": t.get("verb"), "target_state": t["target_state"], "shortest": shortest,
                "scent_correct": (self.scent.get(t["id"]) or {}).get("correct"), "walked": w is not None,
                "success": success, "clicks": clicks, "directness": directness,
                "ease": survey.get("ease"), "confidence": survey.get("confidence"),
            })
        return rows


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
              f"findings {len(f['new'])} new, {len(f['open'])} open, {len(f['fixed'])} fixed")


if __name__ == "__main__":
    main(sys.argv)
