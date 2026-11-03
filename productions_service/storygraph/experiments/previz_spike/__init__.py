"""Blender previz spike (scn_001 Ava enters, scn_004 Pip pushes the cabinet), offline.

`python -m storygraph.experiments.previz_spike --stage render|judge|report --out O`

Runs the production S8_PREVIZ code (`previz.stage.stage.run_previz`, variant `both`) and a
plate-keyframe D1 baseline on the exported production held in memory. Media go to the
experiment prefix `gs://<bucket>/kf_experiments/<project>/…` (Omni needs gs:// inputs) —
never the production prefix — and nothing is written to Firestore.
"""
