"""Time a chapter's builds and captions to its narration audio.

Runs forced alignment (pocketsphinx, free and offline) of the script's own
narration against the voice track, so every [+] cue and every caption lands
on the spoken words. Writes the timings file assemble.py reads with --timings.

    python3 video/align.py SCRIPT.yaml --chapter 1 --audio ch1-voice.mp3 --out ch1.timings.json
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parent))
from assemble import SCENE_TAIL, scene_sentences, segments  # noqa: E402

ONES = "zero one two three four five six seven eight nine ten eleven twelve thirteen fourteen fifteen sixteen seventeen eighteen nineteen".split()
TENS = "_ _ twenty thirty forty fifty sixty seventy eighty ninety".split()
# Words the speech dictionary lacks, in its phone set. Add more here when align.py reports one.
EXTRA_WORDS = {
    "aeration": "EH R EY SH AH N",
    "opord": "OW P AO R D",
    "vetcert": "V EH T S ER T",
    "verc": "V ER K",
}
LEAD = 0.25       # a scene starts this long before its first word
CUE_LEAD = 0.12   # an item appears this long before the words about it


def number_words(n: int) -> list[str]:
    if n < 20:
        return [ONES[n]]
    if n < 100:
        t, o = divmod(n, 10)
        return [TENS[t]] + ([ONES[o]] if o else [])
    if n < 1000:
        h, r = divmod(n, 100)
        return [ONES[h], "hundred"] + (number_words(r) if r else [])
    th, r = divmod(n, 1000)
    return number_words(th) + ["thousand"] + (number_words(r) if r else [])


def spoken_tokens(text: str) -> list[str]:
    """Narration text as the words a speaker says, lowercase, in dictionary form."""
    out: list[str] = []
    t = text.replace("’", "'").replace("$", " dollars ")
    t = re.sub(r"(\d+):(\d\d)", lambda m: f" {m.group(1)} {m.group(2)} ", t)   # 6:30 -> 6 30
    t = re.sub(r"\ba\.m\.", " a m ", t, flags=re.I)
    t = re.sub(r"\bp\.m\.", " p m ", t, flags=re.I)
    for raw in re.findall(r"[A-Za-z0-9']+", t.replace("-", " ")):
        if raw.isdigit():
            out += number_words(int(raw))
        else:
            out.append(raw.lower().strip("'"))
    return [w for w in out if w]


def to_pcm(audio: Path) -> bytes:
    return subprocess.run(["ffmpeg", "-loglevel", "error", "-i", str(audio), "-ac", "1", "-ar", "16000",
                           "-f", "s16le", "-"], check=True, capture_output=True).stdout


def duration(audio: Path) -> float:
    r = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(audio)],
                       check=True, capture_output=True, text=True)
    return float(r.stdout.strip())


def align_words(words: list[str], pcm: bytes) -> list[tuple[str, float, float]]:
    from pocketsphinx import Decoder

    dec = Decoder(samprate=16000, bestpath=False, loglevel="ERROR")
    for w, ph in EXTRA_WORDS.items():
        if dec.lookup_word(w) is None:
            dec.add_word(w, ph, True)
    missing = sorted({w for w in words if dec.lookup_word(w) is None})
    if missing:
        sys.exit(f"Not in the speech dictionary: {', '.join(missing)}. Add them to EXTRA_WORDS in video/align.py.")
    dec.set_align_text(" ".join(words))
    dec.start_utt()
    dec.process_raw(pcm, full_utt=True)
    dec.end_utt()
    dec.set_alignment()
    dec.start_utt()
    dec.process_raw(pcm, full_utt=True)
    dec.end_utt()
    out = []
    for seg in dec.get_alignment():
        name = seg.name
        if name.startswith("<") or name.startswith("[") or name in ("(NULL)",):
            continue
        name = re.sub(r"\(\d+\)$", "", name)
        out.append((name, seg.start / 100.0, (seg.start + seg.duration) / 100.0))
    return out


def scene_plan(sc: dict) -> list[tuple[int, int, str]]:
    """Each spoken word of a scene as (segment index, caption sentence index, word)."""
    seg_of = []
    for gi, seg in enumerate(segments(sc["say"])):
        seg_of += [gi] * len(spoken_tokens(seg))
    plan, k = [], 0
    for ci, sen in enumerate(scene_sentences(sc["say"])):
        for w in spoken_tokens(sen):
            plan.append((seg_of[k] if k < len(seg_of) else seg_of[-1], ci, w))
            k += 1
    return plan


def chapter_words(chapter: dict) -> list[str]:
    return [w for sc in chapter["scenes"] for _g, _c, w in scene_plan(sc)]


def build_timings(chapter: dict, aligned: list[tuple[str, float, float]], total_audio: float) -> list[dict]:
    plan = [(si, gi, ci, w) for si, sc in enumerate(chapter["scenes"]) for gi, ci, w in scene_plan(sc)]
    if len(plan) != len(aligned):
        sys.exit(f"Alignment returned {len(aligned)} words for {len(plan)} in the script. Check the audio matches the script.")
    for (si, gi, ci, w), (name, *_rest) in zip(plan, aligned):
        if w != name:
            sys.exit(f"Word mismatch in scene {si + 1}: script '{w}', audio '{name}'.")

    first, last = {}, {}
    for (si, gi, ci, w), (_n, s, e) in zip(plan, aligned):
        for key in (("scene", si), ("seg", si, gi), ("cap", si, ci)):
            first.setdefault(key, s)
            last[key] = e

    n = len(chapter["scenes"])
    starts = [0.0] + [max(0.0, first[("scene", i)] - LEAD) for i in range(1, n)]
    ends = starts[1:] + [total_audio + SCENE_TAIL]
    out = []
    for si, sc in enumerate(chapter["scenes"]):
        nseg = len(segments(sc["say"]))
        cues = [round(max(starts[si] + 0.4, first[("seg", si, gi)] - CUE_LEAD), 2) for gi in range(1, nseg)]
        caps = [{"start": round(first[("cap", si, ci)], 2), "end": round(last[("cap", si, ci)] + 0.15, 2), "text": sen}
                for ci, sen in enumerate(scene_sentences(sc["say"]))]
        out.append({"id": sc["id"], "start": round(starts[si], 2), "end": round(ends[si], 2), "cues": cues, "captions": caps})
    flat = [c for sc in out for c in sc["captions"]]
    for a, b in zip(flat, flat[1:]):
        a["end"] = min(a["end"], round(b["start"] - 0.05, 2))
    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("script")
    ap.add_argument("--chapter", type=int, required=True)
    ap.add_argument("--audio", required=True)
    ap.add_argument("--out", required=True)
    a = ap.parse_args()
    script = yaml.safe_load(Path(a.script).read_text(encoding="utf-8"))
    chapter = next(c for c in script["chapters"] if c["n"] == a.chapter)
    words = chapter_words(chapter)
    audio = Path(a.audio)
    aligned = align_words(words, to_pcm(audio))
    timings = build_timings(chapter, aligned, duration(audio))
    Path(a.out).write_text(json.dumps(timings, indent=2), encoding="utf-8")
    print(f"Aligned {len(aligned)} words. Chapter runs {timings[-1]['end']:.1f}s. Saved {a.out}")


if __name__ == "__main__":
    main()
