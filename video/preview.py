#!/usr/bin/env python3
"""Build silent previews and a storyboard page for lesson video scripts.

Spends no API credits. Needs Node.js and ffmpeg (see README, "Lesson videos").

    python3 video/preview.py --module five-ws                 every chapter of one module
    python3 video/preview.py --module five-ws --chapters 1    only Chapter 1
    python3 video/preview.py --module five-ws --frames-only   storyboard frames, no MP4s (fast)
    python3 video/preview.py --track core                     every core module with a script

Output, per module:
    output/video/storyboards/<module>/index.html   open this in your browser
    output/video/storyboards/<module>/ch1.mp4 ...  silent previews with captions
    output/video/storyboards/<module>/ch1.vtt ...  caption files
"""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
VIDEO = ROOT / "video"
OUTPUT = ROOT / "output"
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(VIDEO))

try:
    import yaml

    from verc.video_script import check
    from verc.worksheet_pages import workbook_pages
except ModuleNotFoundError as missing:
    sys.exit(f"Missing Python package: {missing.name}. Run: source .venv/bin/activate && pip install -r requirements.txt")


def need(cmd: str, how: str) -> None:
    if not shutil.which(cmd):
        sys.exit(f"{cmd} is not installed. {how}")


def find_script(track: str, number: int, module_id: str) -> Path | None:
    generated = OUTPUT / "video" / "scripts" / track / f"{number:02d}-{module_id}-video.yaml"
    approved = VIDEO / "scripts" / track / f"{number:02d}-{module_id}.yaml"
    return generated if generated.exists() else approved if approved.exists() else None


def run(cmd: list[str]) -> None:
    subprocess.run(cmd, check=True)


def build_module(track: dict, number: int, module: dict, chapters: list[int] | None, frames_only: bool) -> Path | None:
    script_path = find_script(track["id"], number, module["id"])
    if not script_path:
        print(f"- {module['id']}: no video script yet. Run: python3 generate.py --module {module['id']} --kind video")
        return None
    stem = f"{number:02d}-{module['id']}"
    script = yaml.safe_load(script_path.read_text(encoding="utf-8"))
    problems = check(script)
    if problems:
        print(f"- {module['id']}: the script has {len(problems)} problems. Fix them first:")
        for p in problems[:12]:
            print(f"    {p}")
        print(f"  Check again with: python3 video/script_tools.py {script_path.relative_to(ROOT)}")
        return None

    build = OUTPUT / "video" / "build" / stem
    board = OUTPUT / "video" / "storyboards" / stem
    build.mkdir(parents=True, exist_ok=True)
    board.mkdir(parents=True, exist_ok=True)

    wb_md = OUTPUT / "markdown" / track["id"] / f"{stem}-workbook.md"
    pages = workbook_pages(wb_md.read_text(encoding="utf-8")) if wb_md.exists() else {}
    (build / "worksheets.json").write_text(json.dumps(pages), encoding="utf-8")

    all_ch = [c["n"] for c in script["chapters"]]
    pick = [c for c in all_ch if not chapters or c in chapters]
    assets = ",".join(str(p) for p in (OUTPUT / "video" / "assets", VIDEO / "assets"))
    print(f"\n{module['title']}: {script_path.relative_to(ROOT)}")
    render = ["node", str(VIDEO / "render_frames.mjs"), str(script_path), "--out", str(build / "frames"),
              "--assets", assets, "--worksheets", str(build / "worksheets.json")]
    # Storyboard frames for every chapter, then every build step for the chapters to preview.
    run(render + ["--final"])
    if not frames_only:
        run(render + ["--chapters", ",".join(map(str, pick))])
        for n in pick:
            print(f"  encoding Chapter {n} preview...")
            run([sys.executable, str(VIDEO / "assemble.py"), str(script_path), "--frames", str(build / "frames"),
                 "--chapter", str(n), "--out", str(board / f"ch{n}.mp4"), "--burn-captions"])
    run([sys.executable, str(VIDEO / "storyboard.py"), str(script_path), "--frames", str(build / "frames"),
         "--out", str(board), "--previews", str(board)])
    return board / "index.html"


def main() -> None:
    ap = argparse.ArgumentParser(description="Build silent previews and storyboards for lesson video scripts.")
    ap.add_argument("--module", action="append", help="module id (repeat for more)")
    ap.add_argument("--track", choices=["core", "vetcert", "all"])
    ap.add_argument("--chapters", help="chapters to preview, for example 1 or 1,2. Default: all")
    ap.add_argument("--frames-only", action="store_true", help="storyboard frames only, skip the MP4 previews")
    a = ap.parse_args()
    if not a.module and not a.track:
        ap.error("name a --module or a --track")

    need("node", "Install it with: brew install node")
    need("ffmpeg", "Install it with: brew install ffmpeg")
    if not (VIDEO / "node_modules").exists():
        sys.exit("The video tools are not installed yet. Run:\n    cd video && npm install && npx playwright install chromium && cd ..")

    curriculum = yaml.safe_load((ROOT / "content" / "curriculum.yaml").read_text(encoding="utf-8"))
    chapters = [int(x) for x in a.chapters.split(",")] if a.chapters else None
    built = []
    for track in curriculum["tracks"]:
        if a.track not in (None, "all", track["id"]):
            continue
        for number, module in enumerate(track["modules"], start=1):
            if a.module and module["id"] not in a.module:
                continue
            page = build_module(track, number, module, chapters, a.frames_only)
            if page:
                built.append(page)
    if built:
        print("\nStoryboards:")
        for p in built:
            print(f"    open {p.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
