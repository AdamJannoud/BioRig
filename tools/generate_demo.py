"""Render the 90-second BioRig explainer: four scenes at fixed frame counts, silent captioned master.

    .venv/bin/python tools/generate_demo.py                      # 1920x1080, 30 fps -> assets/media/demo_90s.mp4
    .venv/bin/python tools/generate_demo.py --draft              # 854x480, 12 fps review cut
    .venv/bin/python tools/generate_demo.py --voiceover          # also writes demo_90s_voiceover.mp4 (gTTS, network)
    .venv/bin/python tools/generate_demo.py --refresh-facts      # re-read on-chain facts into tools/demo_facts.json

Every segment length is a whole number of frames, so the runtime is exactly TOTAL_SECONDS at any accepted fps.
Every on-chain value on screen comes from tools/demo_facts.json, which --refresh-facts reads from the live proxy.
"""
from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from tools import demo_style as S  # noqa: E402
from tools.demo_scenes import scene1_context, scene2_verify, scene3_mint, scene4_protect  # noqa: E402

TOTAL_SECONDS = 90
SCENES = (scene1_context, scene2_verify, scene3_mint, scene4_protect)
FACTS_PATH = REPO / "tools" / "demo_facts.json"
DEFAULT_OUT = REPO / "assets" / "media" / "demo_90s.mp4"


def frame_plan(fps: int, scenes=SCENES) -> list[int]:
    """Frames per scene. Rejects any fps that cannot hit every boundary on a whole frame."""
    if not isinstance(fps, int) or fps <= 0:
        raise ValueError(f"fps must be a positive integer, got {fps!r}")
    counts = [s.SECONDS * fps for s in scenes]
    if sum(s.SECONDS for s in scenes) != TOTAL_SECONDS:
        raise ValueError(f"scene seconds sum to {sum(s.SECONDS for s in scenes)}, expected {TOTAL_SECONDS}")
    assert sum(counts) == fps * TOTAL_SECONDS, (counts, fps)
    return counts


def scene_starts(scenes=SCENES) -> list[int]:
    out, acc = [], 0
    for s in scenes:
        out.append(acc)
        acc += s.SECONDS
    return out


# --------------------------------------------------------------------------- facts

def refresh_facts(token_id: int = 1) -> dict:
    from dashboard import h3_nullifier
    from dashboard.chain import Chain
    from dashboard.config import load_settings

    settings = load_settings()
    chain = Chain(settings)
    chain.assert_chain()
    ov = chain.overview()
    stats = chain.get_tree_stats(token_id)
    record = chain.find_mint(token_id)
    tba = chain.check_tba(token_id, record)
    if not tba.ok:
        raise RuntimeError("TBA derivations disagree; refusing to put them in the video")
    receipt = chain.get_receipt(record.tx_hash)
    growth = chain.token_logs(chain.core.events.GrowthUpdated(), token_id)
    d = h3_nullifier.derive(-1.2921, 36.8219, "plot-1")
    facts = {
        "chain_id": settings.chain_id,
        "explorer": settings.explorer_url,
        "proxy": chain.proxy,
        "core_implementation": chain.core_implementation(),
        "registry": ov["registry"],
        "account_implementation": ov["implementation"],
        "buffer_pool": ov["bufferPool"],
        "paused": ov["paused"],
        "token_id": token_id,
        "mint_tx": record.tx_hash,
        "mint_block": record.block_number,
        "mint_gas_used": int(receipt.gasUsed),
        "planter": record.planter,
        "tba": tba.stored,
        "tba_bound_token": list(tba.bound_token),
        "dbh": stats.dbh,
        "biomass": stats.biomass,
        "last_updated": stats.last_updated,
        "is_alive": stats.is_alive,
        "spatial_nullifier": "0x" + stats.spatial_nullifier.hex(),
        "growth_updates": len(growth),
        "demo_h3": {"lat": d.lat, "lng": d.lng, "resolution": d.resolution, "cell": d.cell, "salt": d.salt,
                    "nullifier": d.nullifier_hex, "cell_area_m2": round(d.cell_area_m2)},
        "read_at_block": ov["block"],
    }
    FACTS_PATH.write_text(json.dumps(facts, indent=2) + "\n")
    return facts


def load_facts() -> dict:
    if not FACTS_PATH.is_file():
        raise SystemExit(f"{FACTS_PATH} is missing; run with --refresh-facts (needs RPC access)")
    return json.loads(FACTS_PATH.read_text())


# --------------------------------------------------------------------------- rendering

def render_frame(scene_index: int, local_t: float, facts: dict):
    scene = SCENES[scene_index]
    starts = scene_starts()
    img, d = S.new_canvas()
    start = starts[scene_index]
    S.header(d, scene_index + 1, scene.TITLE, f"{S.mmss(start)}–{S.mmss(start + scene.SECONDS)}")
    scene.draw(img, d, local_t, facts)
    S.caption_band(d, scene.CAPTIONS, local_t)
    S.progress(d, start + local_t, TOTAL_SECONDS, starts[1:])
    return img


def ffmpeg_bin() -> str:
    exe = shutil.which("ffmpeg")
    if exe:
        return exe
    import imageio_ffmpeg
    return imageio_ffmpeg.get_ffmpeg_exe()


def render(out: Path, fps: int, size: tuple[int, int], facts: dict, only_scene: int | None = None) -> int:
    counts = frame_plan(fps)
    total = sum(counts)
    if only_scene is None:
        assert total == fps * TOTAL_SECONDS, f"frame total {total} != {fps} * {TOTAL_SECONDS}"
    out.parent.mkdir(parents=True, exist_ok=True)
    cmd = [ffmpeg_bin(), "-y", "-loglevel", "error", "-f", "rawvideo", "-pix_fmt", "rgb24",
           "-s", f"{size[0]}x{size[1]}", "-r", str(fps), "-i", "-",
           "-c:v", "libx264", "-preset", "medium", "-crf", "18", "-pix_fmt", "yuv420p",
           "-movflags", "+faststart", str(out)]
    proc = subprocess.Popen(cmd, stdin=subprocess.PIPE)
    written = 0
    t0 = time.time()
    try:
        for i, n in enumerate(counts):
            if only_scene is not None and i != only_scene:
                continue
            for f in range(n):
                img = render_frame(i, f / fps, facts)
                if img.size != size:
                    img = img.resize(size, resample=3)  # LANCZOS-quality BICUBIC is plenty for the draft
                proc.stdin.write(img.tobytes())
                written += 1
            print(f"  scene {i + 1}: {n} frames ({SCENES[i].SECONDS} s)  [{time.time() - t0:.0f}s]", flush=True)
    finally:
        proc.stdin.close()
        rc = proc.wait()
    if rc != 0:
        raise RuntimeError(f"ffmpeg exited {rc}")
    expected = counts[only_scene] if only_scene is not None else fps * TOTAL_SECONDS
    assert written == expected, f"wrote {written} frames, expected {expected}"
    return written


def voiceover(master: Path, out: Path) -> None:
    """Per-scene gTTS narration, each fitted (padded, or sped up if long) to its scene length, muxed onto the
    silent master. The video stream is copied, so frames and timing are untouched."""
    from gtts import gTTS

    ff = ffmpeg_bin()
    work = master.parent / ".voiceover"
    work.mkdir(exist_ok=True)
    fitted = []
    for i, scene in enumerate(SCENES):
        mp3 = work / f"scene{i + 1}.mp3"
        gTTS(scene.NARRATION, lang="en", tld="com").save(str(mp3))
        dur = float(subprocess.check_output(["ffprobe", "-v", "error", "-show_entries", "format=duration",
                                             "-of", "csv=p=0", str(mp3)]).decode().strip())
        target = scene.SECONDS - 0.4
        tempo = max(1.0, dur / target)
        wav = work / f"scene{i + 1}.wav"
        subprocess.run([ff, "-y", "-loglevel", "error", "-i", str(mp3), "-af",
                        f"atempo={tempo:.4f},apad,atrim=0:{scene.SECONDS}", "-ar", "44100", "-ac", "1", str(wav)],
                       check=True)
        fitted.append(wav)
    concat = work / "list.txt"
    concat.write_text("".join(f"file '{p.name}'\n" for p in fitted))
    track = work / "narration.wav"
    subprocess.run([ff, "-y", "-loglevel", "error", "-f", "concat", "-safe", "0", "-i", str(concat),
                    "-c", "copy", str(track)], check=True)
    subprocess.run([ff, "-y", "-loglevel", "error", "-i", str(master), "-i", str(track), "-map", "0:v", "-map",
                    "1:a", "-c:v", "copy", "-c:a", "aac", "-b:a", "160k", "-t", str(TOTAL_SECONDS),
                    "-movflags", "+faststart", str(out)], check=True)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Render the BioRig 90-second explainer.")
    ap.add_argument("--out", type=Path, default=DEFAULT_OUT)
    ap.add_argument("--fps", type=int, default=None, help="default 30 (12 with --draft)")
    ap.add_argument("--draft", action="store_true", help="854x480 at 12 fps for a quick review")
    ap.add_argument("--voiceover", action="store_true", help="also write <out>_voiceover.mp4 with gTTS narration")
    ap.add_argument("--refresh-facts", action="store_true", help="re-read on-chain facts before rendering")
    ap.add_argument("--scene", type=int, choices=[1, 2, 3, 4], help="render one scene only (review aid)")
    ap.add_argument("--still", type=float, metavar="T", help="write a PNG of global time T seconds and exit")
    args = ap.parse_args(argv)

    facts = refresh_facts() if args.refresh_facts else load_facts()
    fps = args.fps or (12 if args.draft else 30)
    size = (854, 480) if args.draft else (S.W, S.H)

    if args.still is not None:
        starts = scene_starts()
        idx = max(i for i, s in enumerate(starts) if s <= args.still)
        png = args.out.with_suffix(f".t{args.still:g}.png")
        render_frame(idx, args.still - starts[idx], facts).save(png)
        print(png)
        return 0

    only = args.scene - 1 if args.scene else None
    out = args.out if only is None else args.out.with_name(f"{args.out.stem}_scene{args.scene}.mp4")
    print(f"rendering {out} at {size[0]}x{size[1]}, {fps} fps, plan {frame_plan(fps)}")
    frames = render(out, fps, size, facts, only)
    print(f"wrote {frames} frames = {frames / fps:.3f} s -> {out}")
    if args.voiceover and only is None:
        vo = out.with_name(f"{out.stem}_voiceover.mp4")
        voiceover(out, vo)
        print(f"voiceover -> {vo}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
