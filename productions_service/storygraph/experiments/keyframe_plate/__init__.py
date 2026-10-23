"""Offline plate-anchored keyframe validation on an exported production (no prod writes).

`python -m storygraph.experiments.keyframe_plate --export-dir D --project-id P
 --scenes scn_001,scn_004,scn_007 --before-dir B --out O`

Runs the real S8_KEYFRAMES scene code (`keyframes.stage.stage.run_scene`) against an
in-memory `Repo` loaded from the export; blobs are READ from GCS (refs) and WRITTEN only to
the local `--out` directory. Then writes before/after contact sheets and `metrics.json`.
"""
