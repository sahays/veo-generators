"""Video eval engine: named, reusable clip-quality dimensions behind one typed contract.

The S9 critic is a thin gate over `EvalEngine`; the offline eval harness reuses the same engine
(`python -m storygraph.eval.run`). Deterministic metrics are computed once per clip and shared;
VLM-backed dimensions read one sectioned rubric from a single VLM call.
"""
