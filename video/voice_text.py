"""Narration text for the voice, one chapter at a time.

The captions keep the script's spelling. The voice gets a copy with a few words
spelled the way they are said, so the recording matches what align.py expects:
TM 1-04 becomes "T M one oh four", MET becomes "Met", AAR becomes "A-A-R".

    python3 video/voice_text.py video/scripts/tm/TM-1-04.yaml --chapter 1
    python3 video/voice_text.py video/scripts/tm/TM-1-04.yaml --chapter 1 --out ch1.txt
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parent))
from align import CODE_RE, ONES  # noqa: E402

SAY_AS = [
    (r"\bMETs\b", "Mets"),
    (r"\bMET\b", "Met"),
    (r"\bAARs\b", "A-A-Rs"),
    (r"\bAAR\b", "A-A-R"),
    (r"\bSDVOSBs\b", "S-D-V-O-S-Bs"),
    (r"\bSDVOSB\b", "S-D-V-O-S-B"),
    (r"\bVOSBs\b", "V-O-S-Bs"),
    (r"\bVOSB\b", "V-O-S-B"),
    (r"\bUEI\b", "U-E-I"),
    (r"\bEIN\b", "E-I-N"),
    (r"\bCAGE\b", "cage"),
    (r"\bMySBA\b", "My S-B-A"),
    (r"\bNAICS\b", "nakes"),
    (r"\bSWOT\b", "swot"),
]


def say_code(m: re.Match) -> str:
    digit = lambda d: "oh" if d == "0" else ONES[int(d)]
    return f"{m.group(1)} {m.group(2)} {digit(m.group(3))} {digit(m.group(4))} {digit(m.group(5))}"


def tts_text(text: str) -> str:
    t = re.sub(r"\s*\[\+\]\s*", " ", str(text)).strip()
    t = CODE_RE.sub(say_code, t)
    for pattern, said in SAY_AS:
        t = re.sub(pattern, said, t)
    return re.sub(r"\s+", " ", t)


def chapter_text(script: dict, n: int) -> str:
    ch = next(c for c in script["chapters"] if c["n"] == n)
    return "\n\n".join(tts_text(sc["say"]) for sc in ch["scenes"])


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("script")
    ap.add_argument("--chapter", type=int, required=True)
    ap.add_argument("--out")
    a = ap.parse_args()
    text = chapter_text(yaml.safe_load(Path(a.script).read_text(encoding="utf-8")), a.chapter)
    if a.out:
        Path(a.out).write_text(text, encoding="utf-8")
        print(f"{len(text.split())} words, {len(text)} characters. Saved {a.out}")
    else:
        print(text)


if __name__ == "__main__":
    main()
