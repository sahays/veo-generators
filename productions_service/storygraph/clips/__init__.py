"""Omni-ready clip scripts: models, deterministic builders, and partition validation.

Kept import-free on purpose: `storygraph.schema` imports `clips.models`, so this
package initializer must not pull in modules that import `schema` back.
"""
