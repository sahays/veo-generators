"""CLI for the Blender previz spike (render -> judge -> table + sheets)."""

from __future__ import annotations

import argparse
import json
import logging
import os
import subprocess
from pathlib import Path

from google import genai

from ...adapters.vlm import GeminiVLMProvider
from ...repo import Repo
from ..keyframe_ab.report import _truth
from .judge import clip_metrics, handoff, lip_movement
from .render import clip_index, load_repo, run_d1, run_stage

VARIANTS = (
    "previz",
    "E1_omni_restyle",
    "E2_keyframe_restyle",
    "E2v2_keyframe_restyle",
    "D1_plate",
)


def _parse() -> argparse.Namespace:
    p = argparse.ArgumentParser(prog="storygraph.experiments.previz_spike")
    p.add_argument("--stage", choices=("render", "judge"), required=True)
    p.add_argument("--export-dir", required=True, type=Path)
    p.add_argument("--kf-dump", required=True, type=Path)
    p.add_argument("--project-id", default="p-0irbygdv")
    p.add_argument("--scenes", default="scn_001,scn_004")
    p.add_argument("--out", required=True, type=Path)
    p.add_argument(
        "--gcp-project", default=os.getenv("GOOGLE_CLOUD_PROJECT", "aug18-25-3")
    )
    p.add_argument("--bucket", default="aug18-25-3-veo-generators-media")
    return p.parse_args()


def _download(repo_blobs: object, clips: dict[str, dict[str, str]], out: Path) -> None:
    get = getattr(repo_blobs, "get_bytes")
    for sid, row in clips.items():
        for variant, uri in row.items():
            if uri:
                path = out / "clips" / f"{sid}__{variant}.mp4"
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(get(uri))


def render(args: argparse.Namespace) -> None:
    repo = load_repo(
        args.export_dir, args.project_id, args.gcp_project, args.bucket, args.kf_dump
    )
    scenes = args.scenes.split(",")
    run = run_stage(repo, args.gcp_project, scenes, args.out / "work")
    shots = [
        s.id
        for s in repo.list_shots()
        if s.scene_id in scenes and s.clip_index is not None
    ]
    d1_path = args.out / "d1.json"
    d1 = (
        json.loads(d1_path.read_text())
        if d1_path.is_file()
        else run_d1(repo, args.gcp_project, sorted(shots))
    )
    clips = clip_index(repo, d1)
    (args.out / "clips.json").write_text(
        json.dumps({"run": run.model_dump(mode="json"), "clips": clips}, indent=1)
    )
    _download(repo.blobs, clips, args.out)


def _sheet(clip: Path, out: Path) -> None:
    out.parent.mkdir(parents=True, exist_ok=True)
    vf = "fps=1,scale=240:-2,tile=10x1"
    subprocess.run(
        [
            "ffmpeg",
            "-y",
            "-loglevel",
            "error",
            "-i",
            str(clip),
            "-vf",
            vf,
            "-frames:v",
            "1",
            str(out),
        ],
        check=False,
    )


def _speaker(repo: Repo, sid: str) -> str | None:
    shot = repo.get_shot(sid)
    if shot is None or not shot.dialogue_ids:
        return None
    talker = next((c.entity_id for c in shot.cast if c.speaking), None)
    ent = repo.get_entity(talker) if talker else None
    return ent.canonical_name if ent else None


def judge(args: argparse.Namespace) -> None:
    repo = load_repo(
        args.export_dir, args.project_id, args.gcp_project, args.bucket, args.kf_dump
    )
    client = genai.Client(vertexai=True, project=args.gcp_project, location="global")
    vlm = GeminiVLMProvider("gemini-3.8-flash", project=args.gcp_project)
    clips = json.loads((args.out / "clips.json").read_text())["clips"]
    results: dict[str, dict[str, dict[str, float]]] = {}
    for sid in sorted(clips):
        truth = _truth(repo, sid, args.out)
        for variant in VARIANTS:
            clip = args.out / "clips" / f"{sid}__{variant}.mp4"
            if not clip.is_file():
                continue
            m = clip_metrics(client, clip, truth, args.out)
            speaker = _speaker(repo, sid)
            if variant in ("E1_omni_restyle", "D1_plate") and speaker:
                m |= lip_movement(vlm, clip, args.out, speaker)
            results.setdefault(sid, {})[variant] = m
            _sheet(clip, args.out / "sheets" / f"{sid}__{variant}.jpg")
    results["handoff"] = _handoffs(client, args.out, sorted(clips))
    (args.out / "metrics.json").write_text(json.dumps(results, indent=1))


def _handoffs(
    client: genai.Client, out: Path, shot_ids: list[str]
) -> dict[str, dict[str, float]]:
    pairs = list(
        zip(shot_ids, shot_ids[1:], strict=False)
    )  # 001_01->001_02->004_01->004_02
    res: dict[str, dict[str, float]] = {}
    for variant in VARIANTS:
        for a, b in pairs:
            pa, pb = (
                out / "clips" / f"{a}__{variant}.mp4",
                out / "clips" / f"{b}__{variant}.mp4",
            )
            if pa.is_file() and pb.is_file():
                res[f"{variant}:{a}->{b}"] = handoff(client, pa, pb, out)
    return res


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(message)s")
    args = _parse()
    args.out.mkdir(parents=True, exist_ok=True)
    (render if args.stage == "render" else judge)(args)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
