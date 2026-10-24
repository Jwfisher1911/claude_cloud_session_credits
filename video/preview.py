#!/usr/bin/env python3
"""Build silent previews and a storyboard page for lesson video scripts.

Spends no API credits. Needs Node.js and ffmpeg (see README, "Lesson videos").

    python3 video/preview.py --module five-ws                 every chapter of one module
    python3 video/preview.py --module five-ws --chapters 1    only Chapter 1
    python3 video/preview.py --module five-ws --frames-only   storyboard frames, no MP4s (fast)
    python3 video/preview.py --track core                     every core module with a script
    python3 video/preview.py --module battle-rhythm --voiced  final chapters from voice files
    python3 video/preview.py --tm 1-04                         a Payhip training module (video/scripts/tm/TM-1-04.yaml)

Voiced chapters: put the narration for each chapter in
    output/video/voice/<module>/ch1.mp3, ch2.mp3, ...
--voiced times every item and caption to the voice and writes
    output/video/final/<module>/VERC-M1-Ch1.mp4             clean, for course players (add the .vtt)
    output/video/final/<module>/VERC-M1-Ch1-Captioned.mp4   captions burned in, for social and downloads
    output/video/final/<module>/VERC-M1-Ch1.vtt             captions file
    output/video/final/<module>/VERC-M1-Ch1-Audio.mp3       audio-only version

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
TM_DIR = VIDEO / "scripts" / "tm"
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


def level_voice(src: Path, dst: Path) -> None:
    """Two-pass loudness match to -16 LUFS, the usual target for course audio."""
    chain = "highpass=f=70,loudnorm=I=-16:TP=-1.5:LRA=7"
    r = subprocess.run(["ffmpeg", "-hide_banner", "-i", str(src), "-af", chain + ":print_format=json", "-f", "null", "-"],
                       capture_output=True, text=True)
    m = json.loads(r.stderr[r.stderr.rindex("{"):r.stderr.rindex("}") + 1])
    measured = (f":measured_I={m['input_i']}:measured_TP={m['input_tp']}:measured_LRA={m['input_lra']}"
                f":measured_thresh={m['input_thresh']}:offset={m['target_offset']}:linear=true")
    run(["ffmpeg", "-loglevel", "error", "-y", "-i", str(src), "-af", chain + measured, "-ar", "48000", "-ac", "1", str(dst)])


def build_voiced(prefix: str, stem: str, script_path: Path, build: Path, render: list[str],
                 chapters: list[int] | None) -> list[Path]:
    voice_dir = OUTPUT / "video" / "voice" / stem
    final = OUTPUT / "video" / "final" / stem
    final.mkdir(parents=True, exist_ok=True)
    script = yaml.safe_load(script_path.read_text(encoding="utf-8"))
    made = []
    for ch in script["chapters"]:
        n = ch["n"]
        if chapters and n not in chapters:
            continue
        voice = next((voice_dir / f"ch{n}{ext}" for ext in (".mp3", ".wav", ".m4a") if (voice_dir / f"ch{n}{ext}").exists()), None)
        if not voice:
            print(f"  Chapter {n}: no voice file in {voice_dir.relative_to(ROOT)}, skipped")
            continue
        print(f"  Chapter {n}: timing items and captions to {voice.name}...")
        timings = build / f"ch{n}.timings.json"
        run([sys.executable, str(VIDEO / "align.py"), str(script_path), "--chapter", str(n), "--audio", str(voice), "--out", str(timings)])
        leveled = build / f"ch{n}-voice.wav"
        level_voice(voice, leveled)
        run(render + ["--chapters", str(n)])
        base = final / f"{prefix}-Ch{n}"
        for out, burn in ((base.with_suffix(".mp4"), False), (Path(f"{base}-Captioned.mp4"), True)):
            print(f"  Chapter {n}: encoding {out.name}...")
            run([sys.executable, str(VIDEO / "assemble.py"), str(script_path), "--frames", str(build / "frames"),
                 "--chapter", str(n), "--timings", str(timings), "--audio", str(leveled), "--out", str(out)]
                + (["--burn-captions"] if burn else []))
        for extra in (Path(f"{base}-Captioned.vtt"), Path(f"{base}-Captioned.timings.json"), base.with_suffix(".timings.json")):
            extra.unlink(missing_ok=True)
        run(["ffmpeg", "-loglevel", "error", "-y", "-i", str(leveled), "-c:a", "libmp3lame", "-b:a", "128k", "-ar", "44100",
             f"{base}-Audio.mp3"])
        made.append(base.with_suffix(".mp4"))
    return made


def build_module(track: dict, number: int, module: dict, chapters: list[int] | None, frames_only: bool,
                 voiced: bool = False) -> Path | None:
    script_path = find_script(track["id"], number, module["id"])
    if not script_path:
        print(f"- {module['id']}: no video script yet. Run: python3 generate.py --module {module['id']} --kind video")
        return None
    stem = f"{number:02d}-{module['id']}"
    prefix = f"VERC-{'VC' if track['id'] == 'vetcert' else 'M'}{number}"
    wb_md = OUTPUT / "markdown" / track["id"] / f"{stem}-workbook.md"
    return build_script(script_path, stem, prefix, wb_md, chapters, frames_only, voiced)


def build_tm(code: str, chapters: list[int] | None, frames_only: bool, voiced: bool) -> Path | None:
    """A training module from the Payhip catalog, scripted by hand in video/scripts/tm/."""
    script_path = TM_DIR / f"TM-{code}.yaml"
    if not script_path.exists():
        print(f"- TM {code}: no script at {script_path.relative_to(ROOT)}")
        return None
    stem = f"TM-{code}"
    return build_script(script_path, stem, f"VERC-{stem}", TM_DIR / f"{stem}-worksheets.md", chapters, frames_only, voiced)


def build_script(script_path: Path, stem: str, prefix: str, wb_md: Path, chapters: list[int] | None,
                 frames_only: bool, voiced: bool) -> Path | None:
    script = yaml.safe_load(script_path.read_text(encoding="utf-8"))
    problems = check(script)
    if problems:
        print(f"- {stem}: the script has {len(problems)} problems. Fix them first:")
        for p in problems[:12]:
            print(f"    {p}")
        print(f"  Check again with: python3 video/script_tools.py {script_path.relative_to(ROOT)}")
        return None

    build = OUTPUT / "video" / "build" / stem
    board = OUTPUT / "video" / "storyboards" / stem
    build.mkdir(parents=True, exist_ok=True)
    board.mkdir(parents=True, exist_ok=True)

    pages = workbook_pages(wb_md.read_text(encoding="utf-8")) if wb_md.exists() else {}
    (build / "worksheets.json").write_text(json.dumps(pages), encoding="utf-8")

    all_ch = [c["n"] for c in script["chapters"]]
    pick = [c for c in all_ch if not chapters or c in chapters]
    assets = ",".join(str(p) for p in (OUTPUT / "video" / "assets", VIDEO / "assets"))
    print(f"\n{script['title']}: {script_path.relative_to(ROOT)}")
    render = ["node", str(VIDEO / "render_frames.mjs"), str(script_path), "--out", str(build / "frames"),
              "--assets", assets, "--worksheets", str(build / "worksheets.json")]
    if voiced:
        made = build_voiced(prefix, stem, script_path, build, render, chapters)
        for m in made:
            print(f"    {m.relative_to(ROOT)}")
        return made[0].parent if made else None
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
    ap.add_argument("--tm", help="training module codes from video/scripts/tm, for example 1-04 or 1-04,1-05, or all")
    ap.add_argument("--chapters", help="chapters to preview, for example 1 or 1,2. Default: all")
    ap.add_argument("--frames-only", action="store_true", help="storyboard frames only, skip the MP4 previews")
    ap.add_argument("--voiced", action="store_true", help="build final chapters from voice files in output/video/voice/<module>/")
    a = ap.parse_args()
    if not a.module and not a.track and not a.tm:
        ap.error("name a --module, a --track or a --tm")

    need("node", "Install it with: brew install node")
    need("ffmpeg", "Install it with: brew install ffmpeg")
    if not (VIDEO / "node_modules").exists():
        sys.exit("The video tools are not installed yet. Run:\n    cd video && npm install && npx playwright install chromium && cd ..")

    curriculum = yaml.safe_load((ROOT / "content" / "curriculum.yaml").read_text(encoding="utf-8"))
    chapters = [int(x) for x in a.chapters.split(",")] if a.chapters else None
    built = []
    if a.tm:
        codes = sorted(p.stem[3:] for p in TM_DIR.glob("TM-*.yaml")) if a.tm == "all" else a.tm.split(",")
        for code in codes:
            page = build_tm(code.strip(), chapters, a.frames_only, a.voiced)
            if page:
                built.append(page)
    for track in curriculum["tracks"]:
        if not (a.module or a.track):
            break
        if a.track not in (None, "all", track["id"]):
            continue
        for number, module in enumerate(track["modules"], start=1):
            if a.module and module["id"] not in a.module:
                continue
            page = build_module(track, number, module, chapters, a.frames_only, a.voiced)
            if page:
                built.append(page)
    if built:
        print("\nFinal chapters:" if a.voiced else "\nStoryboards:")
        for p in built:
            print(f"    open {p.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
