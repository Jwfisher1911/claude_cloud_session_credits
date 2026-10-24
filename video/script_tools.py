"""Check a VERC lesson video script and show its length.

    python3 video/script_tools.py output/video/scripts/core/02-five-ws-video.yaml
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from verc.video_script import check, load, spoken, stats  # noqa: E402,F401

if __name__ == "__main__":
    s = load(Path(sys.argv[1]))
    probs = check(s)
    total_w = total_m = 0
    for n, title, w, m in stats(s):
        total_w += w
        total_m += m
        print(f"Chapter {n}: {title:<34} {w:4d} words  ~{int(m)}:{int(m % 1 * 60):02d}")
    print(f"Total: {total_w} words  ~{int(total_m)}:{int(total_m % 1 * 60):02d}")
    print("\n".join(probs) if probs else "Checks: clean")
    sys.exit(1 if probs else 0)
