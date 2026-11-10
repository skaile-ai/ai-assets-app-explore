# Feature `saliency`

Read this only when `run.json.features.saliency` is true. It adds step 5b, the `R-salience` findings of step 7 and the `saliency_gallery` block of step 9.

## 5b. Score every screenshot

```bash
PY=$(bash <skill dir>/saliency/setup.sh) && "$PY" <skill dir>/saliency/run.py <reports dir>/<stem>.data <reports dir>/<stem>.media
```

`setup.sh` installs once into `~/.cache/app-explore/saliency/`: a python3.11 venv with TensorFlow, tf-keras and Pillow, and the UMSI++ weights `umsi++.hdf5`. The weights are downloaded from the UEyes site on the user's machine (the skill does not ship them), and the zip's sha256 is checked before it is unpacked. It prints the venv's python; later calls skip what exists.

`run.py` predicts where a first look lands on each screenshot with UMSI++ (UEyes, CHI '23, trained on eye tracking over UI screenshots). It writes `<stem>.media/<id>.sal.png` (heatmap over the screenshot, the primary action outlined) and `<stem>.data/saliency.json`:

```
{<id>: {primary_mark, primary_source, primary_share, primary_rank, marks, shares: {<mark>: share}, top_marks: [{mark, share}], rendered_ms}}
```

A mark's `share` is its attention per pixel against the page average (saliency mass in its box over the box's share of the page). `shares` holds every ranked mark, highest first; `marks` is their count. The primary mark is the action `perceive.json` `extract` flags `primary`, else its first action with a mark.

`setup.sh` fails (exit 2: no python3.11; exit 3: the downloaded zip's sha256 changed; else pip or the download failed): record why and go on with step 6:

```bash
python3 <skill dir>/saliency/run.py <reports dir>/<stem>.data <reports dir>/<stem>.media --error "<setup.sh's last stderr line>"
```

`run.py` records its own failures the same way. `run.json.saliency_error` reaches the report's `run_details`.

**Done when** `saliency.json` has an entry per `graph.json` state and each has its `<id>.sal.png`, or `run.json.saliency_error` is set.

## Step 7: `R-salience`

With `saliency.json` present, `analyze.py` adds `R-salience` findings (source `saliency`, marked on the primary action) on each screen whose primary action ranks outside the top `top_frac` of its marks by `share`, or whose top mark has over `max_ratio` × the primary's `share` (rubric.json rule thresholds).

## Step 9: `saliency_gallery`

One heatmap per scored state, caption the primary action's attention rank, notes its `R-salience` findings. It is a gallery of its own, so the Before/Now toggle of `screens_gallery` stays the `since` comparison. `run_details` names the attention model and its sources, or `saliency_error`.
