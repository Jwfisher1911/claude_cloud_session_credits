"""Assemble one chapter of a VERC lesson video from rendered frames.

Each scene is a run of build frames (b0, b1, ...). A build appears on its [+]
cue in the narration. Without a voice track, cue times come from an estimate of
145 words per minute, which gives a silent preview (an animatic). With a voice
track, pass --timings, a JSON file of real cue times.

Outputs an MP4 (1920x1080, 30 fps), a WebVTT caption file, and the timings
used, so the same cues drive the captions and the builds.

Usage:
    python3 video/assemble.py SCRIPT.yaml --frames DIR --chapter 1 --out ch1.mp4
        [--audio voice.wav] [--timings ch1-timings.json] [--burn-captions]
"""

from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
import tempfile
from pathlib import Path

import yaml

HERE = Path(__file__).resolve().parent
WPM = 145
BUILD_FADE = 0.35
SCENE_FADE = 0.5
SCENE_TAIL = 0.8          # hold after the last word of a scene
SENTENCE_PAUSE = 0.28     # estimated pause after each sentence
MAX_CAPTION_CHARS = 84


def segments(say: str) -> list[str]:
    """Narration split at the [+] markers. Segment k starts build k."""
    return [s.strip() for s in say.split("[+]")]


def sentences(text: str) -> list[str]:
    parts = re.split(r"(?<=[.?!])\s+", text.strip())
    out: list[str] = []
    for p in parts:
        if not p:
            continue
        # Split a long sentence into balanced chunks, preferring commas.
        n = -(-len(p) // MAX_CAPTION_CHARS)
        while n > 1:
            target = len(p) // n
            spaces = [m.start() for m in re.finditer(" ", p)]
            commas = [i + 1 for i in (m.start() for m in re.finditer(", ", p)) if abs(i - target) < 18]
            cut = min(commas or spaces, key=lambda i: abs(i - target))
            out.append(p[:cut].strip())
            p = p[cut:].strip()
            n -= 1
        out.append(p)
    return out


def words(text: str) -> int:
    return len(text.split())


def estimate(chapter: dict) -> list[dict]:
    """Estimated timings: per scene, its start, its cue times, and caption cues."""
    t = 0.0
    out = []
    for sc in chapter["scenes"]:
        start = t
        cues, caps = [], []
        for k, seg in enumerate(segments(sc["say"])):
            if k > 0:
                cues.append(round(t, 2))
            for sen in sentences(seg):
                d = words(sen) / WPM * 60 + SENTENCE_PAUSE
                caps.append({"start": round(t, 2), "end": round(t + d - 0.08, 2), "text": sen})
                t += d
        t += SCENE_TAIL
        out.append({"id": sc["id"], "start": round(start, 2), "end": round(t, 2), "cues": cues, "captions": caps})
    return out


def vtt_time(x: float) -> str:
    h, rem = divmod(x, 3600)
    m, s = divmod(rem, 60)
    return f"{int(h):02d}:{int(m):02d}:{s:06.3f}"


def write_vtt(timings: list[dict], path: Path) -> None:
    lines = ["WEBVTT", ""]
    for sc in timings:
        for c in sc["captions"]:
            lines += [f"{vtt_time(c['start'])} --> {vtt_time(c['end'])}", c["text"], ""]
    path.write_text("\n".join(lines), encoding="utf-8")


def caption_font_dir(tmp: Path) -> Path:
    """libass needs TTF files. Convert the Public Sans woff2 once."""
    from fontTools.ttLib import TTFont

    d = tmp / "fonts"
    d.mkdir(exist_ok=True)
    src = HERE / "node_modules/@fontsource/public-sans/files/public-sans-latin-600-normal.woff2"
    f = TTFont(str(src))
    f.flavor = None
    f.save(str(d / "PublicSans-SemiBold.ttf"))
    return d


def build_states(chapter_n: int, chapter: dict, frames: Path, timings: list[dict]) -> list[tuple[Path, float, float]]:
    """(image, start, fade-in duration) for every build state, in order."""
    manifest = json.loads((frames / "manifest.json").read_text())
    by_scene = {m["scene"]: m for m in manifest if m["chapter"] == chapter_n}
    states = []
    for sc, tm in zip(chapter["scenes"], timings):
        files = by_scene[sc["id"]]["files"]
        if len(files) != len(tm["cues"]) + 1:
            raise SystemExit(f"{sc['id']}: {len(files)} frames but {len(tm['cues'])} cues. Re-render all builds.")
        states.append((frames / files[0], tm["start"], SCENE_FADE))
        for f, cue in zip(files[1:], tm["cues"]):
            states.append((frames / f, cue, BUILD_FADE))
    return states


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("script")
    ap.add_argument("--frames", required=True)
    ap.add_argument("--chapter", type=int, required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--audio")
    ap.add_argument("--timings")
    ap.add_argument("--burn-captions", action="store_true")
    a = ap.parse_args()

    script = yaml.safe_load(Path(a.script).read_text(encoding="utf-8"))
    chapter = next(c for c in script["chapters"] if c["n"] == a.chapter)
    timings = json.loads(Path(a.timings).read_text()) if a.timings else estimate(chapter)
    out = Path(a.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    write_vtt(timings, out.with_suffix(".vtt"))
    out.with_suffix(".timings.json").write_text(json.dumps(timings, indent=2))

    states = build_states(a.chapter, chapter, Path(a.frames), timings)
    total = timings[-1]["end"]
    # Input i lasts until state i+1 starts, plus the overlap of the next fade.
    inputs, lens = [], []
    for i, (img, start, _) in enumerate(states):
        nxt_start = states[i + 1][1] if i + 1 < len(states) else total
        nxt_fade = states[i + 1][2] if i + 1 < len(states) else 0
        L = max(0.1, nxt_start - start + nxt_fade)
        lens.append(L)
        inputs += ["-loop", "1", "-framerate", "30", "-t", f"{L:.3f}", "-i", str(img)]

    fc, prev = [], "0:v"
    for i in range(1, len(states)):
        fade = states[i][2]
        off = states[i][1]  # see docstring math: offset equals the state's start
        fc.append(f"[{prev}][{i}:v]xfade=transition=fade:duration={fade}:offset={off:.3f}[x{i}]")
        prev = f"x{i}"
    with tempfile.TemporaryDirectory() as td:
        tmp = Path(td)
        last = prev
        if a.burn_captions:
            fonts = caption_font_dir(tmp)
            vtt = tmp / "c.vtt"
            shutil.copy(out.with_suffix(".vtt"), vtt)
            style = ("FontName=Public Sans SemiBold,FontSize=13,PrimaryColour=&H00F7F5EE,BackColour=&H99202F39,"
                     "BorderStyle=4,Outline=0,Shadow=0,MarginV=34,Alignment=2")
            fc.append(f"[{last}]subtitles={vtt}:fontsdir={fonts}:force_style='{style}'[cap]")
            last = "cap"
        fc.append(f"[{last}]format=yuv420p[v]")
        cmd = ["ffmpeg", "-loglevel", "error", "-y", *inputs]
        if a.audio:
            cmd += ["-i", a.audio]
        cmd += ["-filter_complex", ";".join(fc), "-map", "[v]"]
        if a.audio:
            cmd += ["-map", f"{len(states)}:a", "-c:a", "aac", "-b:a", "160k", "-ar", "48000"]
        cmd += ["-c:v", "libx264", "-preset", "faster", "-crf", "20", "-r", "30",
                "-colorspace", "bt709", "-color_primaries", "bt709", "-color_trc", "bt709",
                "-t", f"{total:.3f}", "-movflags", "+faststart", str(out)]
        subprocess.run(cmd, check=True)
    print(f"{out}  {total:.1f}s  {len(states)} frames, captions {out.with_suffix('.vtt').name}")


if __name__ == "__main__":
    main()
