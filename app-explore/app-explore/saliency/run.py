#!/usr/bin/env python3
"""Saliency of every crawled screen (feature `saliency`): where a first look lands, predicted by UMSI++ (umsi_tf.py).

    PY=$(bash saliency/setup.sh) && "$PY" saliency/run.py <stem>.data <stem>.media
    python3 saliency/run.py <stem>.data <stem>.media --error "<why setup failed>"

Per state of graph.json (screenshot <stem>.media/<id>.png, marks from screens/<id>.json):
- <stem>.media/<id>.sal.png: the heatmap over the screenshot, the primary action's box outlined; same size as the
  screenshot, so mark boxes and gallery notes line up.
- <stem>.data/saliency.json {<state>: {primary_mark, primary_source, primary_share, primary_rank, marks, shares:
  {<mark>: share}, top_marks: [{mark, share}], rendered_ms}}. `share` of a mark = the saliency mass inside its box
  divided by the box's share of the page area: 1 = page average, 3 = three times as much attention per pixel as the
  page average. `shares` holds every ranked mark, highest first; `marks` is their count, `top_marks` the first 5.
  `primary_rank` 1-based among the `marks` marks by share. The primary mark is the action perceive.json `extract`
  flags `primary` (primary_source "extract"), else its first action with a mark ("first-action"), else null.
On a failure (and with --error) run.json gets `saliency_error` and saliency.json is removed (no R-salience from a
stale run); a success clears `saliency_error`.
With the feature off (run.json features over rubric.json defaults) the script writes nothing and exits 0.
Weights: $APP_EXPLORE_SALIENCY_HOME/umsi++.hdf5, default ~/.cache/app-explore/saliency (setup.sh puts them there).
"""
import json
import os
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
HOME = Path(os.environ.get("APP_EXPLORE_SALIENCY_HOME") or Path.home() / ".cache" / "app-explore" / "saliency")
TOP = 5
# inferno-like ramp for the overlay (value 0..1 -> RGB)
RAMP = [(0.0, (0, 0, 4)), (0.25, (87, 16, 110)), (0.5, (188, 55, 84)), (0.75, (249, 142, 9)), (1.0, (252, 255, 164))]
OUTLINE = (0, 229, 255)


def load(path, default=None):
    try:
        return json.loads(Path(path).read_text())
    except (FileNotFoundError, json.JSONDecodeError):
        return default


def patch_run(data, **kv):
    """Shallow-merge kv into run.json (tmp file + rename); a None value removes the key. A missing run.json starts
    empty; one that does not parse raises (never overwritten with kv alone)."""
    p = data / "run.json"
    try:
        run = json.loads(p.read_text())
    except FileNotFoundError:
        run = {}
    for k, v in kv.items():
        if v is None:
            run.pop(k, None)
        else:
            run[k] = v
    tmp = p.with_name(f"run.json.{os.getpid()}.{os.urandom(4).hex()}.tmp")
    tmp.write_text(json.dumps(run, indent=2, ensure_ascii=False))
    os.replace(tmp, p)


def feature_on(data):
    rubric = load(HERE.parent / "rubric.json", {})
    features = {**rubric.get("features", {}), **(load(data / "run.json", {}).get("features") or {})}
    return bool(features.get("saliency"))


def primary_of(extract, have):
    actions = [a for a in (extract or {}).get("actions") or [] if a.get("mark") in have]
    flagged = [a for a in actions if a.get("primary")]
    if flagged:
        return flagged[0]["mark"], "extract"
    if actions:
        return actions[0]["mark"], "first-action"
    return None, None


def mark_shares(sal, marks):
    """{mark n: share}: mass in the box (viewport percent, clipped to the image) over the box's area fraction."""
    import numpy as np
    H, W = sal.shape
    out = {}
    for m in marks:
        b = m.get("box") or {}
        x0, y0 = max(0, round(b.get("x", 0) * W / 100)), max(0, round(b.get("y", 0) * H / 100))
        x1 = min(W, round((b.get("x", 0) + b.get("w", 0)) * W / 100))
        y1 = min(H, round((b.get("y", 0) + b.get("h", 0)) * H / 100))
        if x1 <= x0 or y1 <= y0:
            continue
        mass = float(np.sum(sal[y0:y1, x0:x1], dtype=np.float64))
        out[m["n"]] = round(mass / ((x1 - x0) * (y1 - y0) / (W * H)), 3)
    return out


def overlay(shot, sal, box, out):
    import numpy as np
    from PIL import Image, ImageDraw
    v = sal / sal.max()
    xs = [s for s, _ in RAMP]
    heat = np.stack([np.interp(v, xs, [c[i] for _, c in RAMP]) for i in range(3)], -1)
    a = (v ** 0.7)[..., None] * 0.85
    base = np.asarray(Image.open(shot).convert("RGB"), np.float32)
    img = Image.fromarray((heat * a + base * (1 - a)).astype(np.uint8))
    if box:
        H, W = sal.shape
        d = ImageDraw.Draw(img)
        d.rectangle([box["x"] * W / 100, box["y"] * H / 100, (box["x"] + box["w"]) * W / 100,
                     (box["y"] + box["h"]) * H / 100], outline=OUTLINE, width=max(2, W // 400))
    img.quantize(64).save(out, optimize=True)


def run(data, media):
    import umsi_tf
    weights = HOME / "umsi++.hdf5"
    if not weights.is_file():
        raise RuntimeError(f"no weights at {weights}; run saliency/setup.sh")
    graph = load(data / "graph.json")
    if graph is None:
        raise RuntimeError(f"{data / 'graph.json'} not found")
    perceive = load(data / "perceive.json", {})
    model = umsi_tf.load("umsi++", str(weights))
    out = {}
    for s in graph["states"]:
        sid = s["id"]
        shot = media / f"{sid}.png"
        if not shot.is_file():
            continue
        marks = (load(data / "screens" / f"{sid}.json", {}) or {}).get("marks") or []
        t = time.time()
        sal = umsi_tf.predict(model, str(shot))
        ms = round((time.time() - t) * 1000)
        shares = mark_shares(sal, marks)
        ranked = sorted(shares, key=lambda n: -shares[n])
        pm, src = primary_of((perceive.get(sid) or {}).get("extract"), shares)
        overlay(shot, sal, next((m["box"] for m in marks if m["n"] == pm), None), media / f"{sid}.sal.png")
        out[sid] = {
            "primary_mark": pm, "primary_source": src,
            "primary_share": shares.get(pm), "primary_rank": ranked.index(pm) + 1 if pm is not None else None,
            "marks": len(ranked), "shares": {n: shares[n] for n in ranked},
            "top_marks": [{"mark": n, "share": shares[n]} for n in ranked[:TOP]],
            "rendered_ms": ms,
        }
    (data / "saliency.json").write_text(json.dumps(out, indent=2))
    return out


def main(argv):
    args = argv[1:]
    err = None
    if len(args) == 4 and args[2] == "--error":
        args, err = args[:2], args[3]
    if len(args) != 2:
        sys.exit("usage: run.py <stem>.data <stem>.media [--error <message>]")
    data, media = Path(args[0]), Path(args[1])
    if not data.is_dir() or not media.is_dir():
        sys.exit(f"saliency: {data} and {media} must be directories")
    if not feature_on(data):
        print("saliency: feature off, nothing written")
        return
    if err is not None:
        patch_run(data, saliency_error=err)
        (data / "saliency.json").unlink(missing_ok=True)
        print(f"saliency: skipped ({err})")
        return
    sys.path.insert(0, str(HERE))
    try:
        out = run(data, media)
    except Exception as e:  # recorded for the report; the run goes on without saliency
        patch_run(data, saliency_error=f"{type(e).__name__}: {e}")
        (data / "saliency.json").unlink(missing_ok=True)
        print(f"saliency: failed, recorded in run.json saliency_error: {e}", file=sys.stderr)
        sys.exit(1)
    patch_run(data, saliency_error=None)
    low = [sid for sid, v in out.items() if v["primary_rank"] and v["primary_rank"] > 1]
    print(f"saliency: {len(out)} screens, {sum(v['rendered_ms'] for v in out.values())} ms model time, "
          f"primary not the top mark on {len(low)} → {data / 'saliency.json'}")


if __name__ == "__main__":
    main(sys.argv)
