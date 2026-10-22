"""Golden-set calibration of the eval gate (S9 critic) — see docs/eval/eval_calibration_v1.md.

Stages (typed JSONL hand-offs, see `contracts.py`):
1. `scorer`   — re-score golden clips with the live engine into a cached `CachedScore` JSONL.
2. `agreement` — engine vs golden: pass/fail P/R/F1, per-dimension Spearman, defect hit rates.
3. `search`   — leave-one-shot-out threshold / hard-gate / weight search with held-out metrics.
"""
