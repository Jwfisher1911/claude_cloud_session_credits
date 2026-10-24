"""Build a storyboard page for a lesson video script.

The page shows each scene's frame beside its narration for the chapters you
rendered, an optional preview video, and the full script for every chapter.

Usage:
    python3 video/storyboard.py SCRIPT.yaml --frames DIR --out DIR [--samples DIR] [--previews DIR]

--previews is a folder holding ch1.mp4, ch2.mp4, ... Each one found is shown
above its chapter's storyboard.
"""

from __future__ import annotations

import argparse
import html
import json
import shutil
import subprocess
from pathlib import Path

import yaml

import sys
sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from assemble import estimate  # noqa: E402
from verc.video_script import spoken, stats  # noqa: E402,F401

LAYOUT_NAMES = {
    "title": "Title card", "outline": "Chapter map", "photo": "Photo statement", "list": "List",
    "compare": "Three-way compare", "steps": "Numbered steps", "example": "Example card",
    "fieldnote": "Field note", "task": "Your task today", "end": "Up next", "bignum": "Big number",
    "statement": "Statement", "card": "MET card", "tiles": "Four tiles", "grid": "Weekly grid",
    "table": "Table", "numbers": "Number tiles", "checklist": "Checklist",
}


def esc(s) -> str:
    return html.escape(str(s or ""))


def narration_html(say: str) -> str:
    parts = [esc(p.strip()) for p in say.split("[+]")]
    out = parts[0]
    for p in parts[1:]:
        out += ' <span class="cue" title="Next item appears on screen">+</span> ' + p
    return out


def headline(sc: dict) -> str:
    for k in ("headline", "heading", "text", "next", "name"):
        if sc.get(k):
            return str(sc[k])
    if sc["layout"] == "compare":
        return " / ".join(c["label"] for c in sc["cols"])
    return sc["id"]


def mmss(x: float) -> str:
    return f"{int(x // 60)}:{int(x % 60):02d}"


def to_jpg(src: Path, dst: Path) -> None:
    dst.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(["ffmpeg", "-loglevel", "error", "-y", "-i", str(src), "-vf", "scale=1280:-2", "-q:v", "3", str(dst)], check=True)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("script")
    ap.add_argument("--frames", required=True)
    ap.add_argument("--samples")
    ap.add_argument("--out", required=True)
    ap.add_argument("--previews")
    a = ap.parse_args()

    script = yaml.safe_load(Path(a.script).read_text(encoding="utf-8"))
    out = Path(a.out)
    (out / "frames").mkdir(parents=True, exist_ok=True)
    manifest = json.loads((Path(a.frames) / "manifest.json").read_text())
    final = {(m["chapter"], m["scene"]): Path(a.frames) / m["files"][-1] for m in manifest}
    samples = []
    if a.samples:
        for m in json.loads((Path(a.samples) / "manifest.json").read_text()):
            samples.append((m["chapter"], m["scene"], Path(a.samples) / m["files"][-1]))

    st = stats(script)
    total_words = sum(r[2] for r in st)
    total_min = sum(r[3] for r in st)
    rendered = sorted({c for c, _ in final})

    boards = []
    for ch in script["chapters"]:
        if ch["n"] not in rendered:
            continue
        tm = {t["id"]: t for t in estimate(ch)}
        cards = []
        for i, sc in enumerate(ch["scenes"], 1):
            img = f"frames/ch{ch['n']}-{i:02d}.jpg"
            to_jpg(final[(ch["n"], sc["id"])], out / img)
            t = tm[sc["id"]]
            cards.append(f"""
      <li class="scene">
        <img src="{img}" alt="Frame: {esc(headline(sc))}" loading="lazy" width="1280" height="720">
        <div class="meta">
          <p class="sid"><span>{i:02d}</span> {esc(LAYOUT_NAMES.get(sc['layout'], sc['layout']))} <span class="time">{mmss(t['start'])} to {mmss(t['end'])}</span></p>
          <p class="say">{narration_html(sc['say'])}</p>
        </div>
      </li>""")
        video = ""
        mp4 = Path(a.previews) / f"ch{ch['n']}.mp4" if a.previews else None
        if mp4 and mp4.exists():
            if mp4.resolve() != (out / mp4.name).resolve():
                shutil.copy(mp4, out / mp4.name)
            video = f"""
    <video controls preload="metadata" playsinline poster="frames/ch{ch['n']}-01.jpg"><source src="{mp4.name}" type="video/mp4"></video>
    <p class="note">Silent preview with captions, timed to an estimated reading pace. With a voice track, every cue follows the voice.</p>"""
        boards.append(f"""
<section class="band" aria-labelledby="sb{ch['n']}">
  <div class="wrap">
    <p class="eyebrow">Chapter {ch['n']} of {len(script['chapters'])}</p>
    <h2 style="margin-bottom:18px" id="sb{ch['n']}">{esc(ch['title'])}</h2>{video}
    <p class="lede">Each frame is the scene with all of its items showing. A gold <span class="cue">+</span> in the narration marks the moment the next item appears.</p>
    <ol class="scenes">{''.join(cards)}
    </ol>
  </div>
</section>""")

    sample_html = ""
    if samples:
        figs = []
        for c, sid, f in samples:
            ch = next(x for x in script["chapters"] if x["n"] == c)
            img = f"frames/sample-ch{c}-{sid}.jpg"
            to_jpg(f, out / img)
            figs.append(f'<figure><img src="{img}" alt="Sample frame from Chapter {c}" loading="lazy" width="1280" height="720"><figcaption>Chapter {c} · {esc(ch["title"])}</figcaption></figure>')
        sample_html = f"""
<section class="band alt" aria-labelledby="smp">
  <div class="wrap">
    <p class="eyebrow">Later chapters</p>
    <h2 id="smp">Sample frames</h2>
    <p class="lede">The main visual from each of the later chapters.</p>
    <div class="samples">{''.join(figs)}</div>
  </div>
</section>"""

    script_parts = []
    for ch in script["chapters"]:
        n, title, w, m = next(r for r in st if r[0] == ch["n"])
        rows = "".join(
            f'<li><p class="hl">{esc(headline(sc))}</p><p class="say">{narration_html(sc["say"])}</p></li>'
            for sc in ch["scenes"])
        script_parts.append(f"""
    <details{' open' if ch['n'] not in rendered else ''}>
      <summary><span class="chn">Chapter {n}</span> {esc(title)} <span class="time">{w} words · about {mmss(m * 60)}</span></summary>
      <ol class="lines">{rows}</ol>
    </details>""")

    track_label = "VetCert Readiness" if script.get("track") == "vetcert" else "VERC Core"
    page = f"""<title>{esc(script.get('short') or script['title'])} Storyboard</title>
<meta name="claude:viewport-fit-sides" content="cover">
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Barlow+Condensed:wght@700;800&family=IBM+Plex+Mono:wght@400;500&family=Public+Sans:wght@400;600;700&display=swap">
<style>
/* Layout: one reading column of bands, frame-left / narration-right rows that stack on phones.
   Single dark look on purpose: it matches the Harbor Dawn video frames. */
:root {{
  --ground:#0E3D4A; --deep:#0A2F39; --panel:#0C3542; --paper:#EEF5F7; --muted:#B9CDD3; --main:#7DB9F2; --accent:#F2C14E;
  --rule:rgba(125,185,242,.22);
  --display:"Barlow Condensed", "Arial Narrow", sans-serif; --body:"Public Sans", system-ui, sans-serif; --mono:"IBM Plex Mono", ui-monospace, monospace;
  color-scheme: dark;
}}
body {{ background:var(--deep); color:var(--paper); font-family:var(--body); font-size:17px; line-height:1.55; }}
.wrap {{ max-width:1180px; margin:0 auto; padding-left:max(16px, env(safe-area-inset-left, 0px)); padding-right:max(16px, env(safe-area-inset-right, 0px)); }}
.band {{ padding-block:56px; border-top:1px solid var(--rule); }}
.band.alt {{ background:var(--panel); }}
.top {{ background:var(--ground); padding-block:56px 44px;
  background-image:repeating-linear-gradient(0deg, rgba(125,185,242,.08) 0 1px, transparent 1px 64px), repeating-linear-gradient(90deg, rgba(125,185,242,.08) 0 1px, transparent 1px 64px); }}
.eyebrow {{ font-family:var(--mono); font-size:13px; letter-spacing:.16em; text-transform:uppercase; color:var(--accent); margin:0 0 10px; }}
h1, h2 {{ font-family:var(--display); font-weight:800; line-height:.98; margin:0; text-wrap:balance; }}
h1 {{ font-size:clamp(44px, 7vw, 84px); }}
h2 {{ font-size:clamp(32px, 4.4vw, 48px); }}
.lede {{ color:var(--muted); max-width:66ch; margin:14px 0 26px; }}
.facts {{ display:flex; flex-wrap:wrap; gap:12px; margin:26px 0 0; padding:0; list-style:none; }}
.facts li {{ border:1px solid var(--rule); border-radius:10px; padding:10px 16px; background:rgba(10,47,57,.6); }}
.facts b {{ display:block; font-family:var(--display); font-size:28px; line-height:1.1; font-variant-numeric:tabular-nums; }}
.facts span {{ font-family:var(--mono); font-size:12px; letter-spacing:.12em; text-transform:uppercase; color:var(--main); }}
video {{ width:100%; max-width:100%; aspect-ratio:16/9; background:#000; border-radius:10px; display:block; }}
.cue {{ display:inline-flex; align-items:center; justify-content:center; width:1.25em; height:1.25em; border-radius:50%; background:var(--accent); color:var(--ground);
  font-family:var(--mono); font-weight:500; font-size:.8em; line-height:1; vertical-align:.08em; }}
.scenes {{ list-style:none; margin:0; padding:0; display:flex; flex-direction:column; gap:22px; }}
.scene {{ display:grid; grid-template-columns:minmax(0, 520px) minmax(0, 1fr); gap:28px; align-items:start; padding-bottom:22px; border-bottom:1px solid var(--rule); }}
.scene img {{ width:100%; height:auto; border-radius:8px; display:block; box-shadow:0 10px 30px rgba(0,0,0,.35); }}
.meta {{ min-width:0; }}
.sid {{ font-family:var(--mono); font-size:13px; letter-spacing:.1em; text-transform:uppercase; color:var(--main); margin:4px 0 10px; display:flex; flex-wrap:wrap; gap:6px 12px; align-items:baseline; }}
.sid span:first-child {{ color:var(--accent); }}
.time {{ color:var(--muted); letter-spacing:.04em; font-variant-numeric:tabular-nums; }}
.say {{ margin:0; max-width:62ch; }}
.note {{ color:var(--muted); font-size:14px; margin:10px 0 0; }}
video + .note + .lede {{ margin-top:30px; }}
.samples {{ display:grid; grid-template-columns:repeat(auto-fit, minmax(260px, 1fr)); gap:20px; }}
figure {{ margin:0; }}
figure img {{ width:100%; height:auto; border-radius:8px; display:block; }}
figcaption {{ font-family:var(--mono); font-size:12px; letter-spacing:.1em; text-transform:uppercase; color:var(--muted); margin-top:8px; }}
details {{ border-top:1px solid var(--rule); }}
details:last-child {{ border-bottom:1px solid var(--rule); }}
summary {{ cursor:pointer; padding:18px 0; font-family:var(--display); font-weight:700; font-size:28px; display:flex; flex-wrap:wrap; gap:6px 14px; align-items:baseline; }}
summary:focus-visible {{ outline:2px solid var(--accent); outline-offset:4px; }}
summary .chn {{ color:var(--accent); }}
summary .time {{ font-family:var(--mono); font-weight:400; font-size:13px; letter-spacing:.06em; }}
.lines {{ margin:0 0 24px; padding-left:1.6em; display:flex; flex-direction:column; gap:14px; }}
.lines li::marker {{ color:var(--main); font-family:var(--mono); font-size:13px; }}
.hl {{ font-weight:700; margin:0 0 2px; }}
.lines .say {{ color:var(--muted); }}
.foot {{ padding-block:34px 48px; color:var(--muted); font-size:14px; border-top:1px solid var(--rule); }}
@media (max-width:760px) {{ .scene {{ grid-template-columns:minmax(0, 1fr); gap:14px; }} }}
</style>

<header class="top">
  <div class="wrap">
    <p class="eyebrow">{track_label} · Module {script['module']} · Lesson video</p>
    <h1>{esc(script['title'])}</h1>
    <p class="lede">Narration script and frames for the video version of the lesson guide. One chapter per lesson, each ending with a workbook task.</p>
    <ul class="facts">
      <li><b>{len(script['chapters'])}</b><span>Chapters</span></li>
      <li><b>{total_words:,}</b><span>Words of narration</span></li>
      <li><b>About {mmss(total_min * 60)}</b><span>Total run time</span></li>
      <li><b>1920 × 1080</b><span>16:9, captions on</span></li>
    </ul>
  </div>
</header>
{''.join(boards)}
{sample_html}
<section class="band" aria-labelledby="scr">
  <div class="wrap">
    <p class="eyebrow">Full script</p>
    <h2 id="scr">Narration, all chapters</h2>
    <p class="lede">Read these aloud as written if you record the voice yourself. Pause briefly at each <span class="cue">+</span>.</p>
    {''.join(script_parts)}
  </div>
</section>
<footer class="foot"><div class="wrap">VERC is a d/b/a of Casa Concepts LLC. VERC is not affiliated with DoD, SBA or VA. The appearance of U.S. Department of Defense (DoD) visual information does not imply or constitute DoD endorsement. Imagery: DVIDS.</div></footer>
"""
    (out / "index.html").write_text(page, encoding="utf-8")
    print(out / "index.html")


if __name__ == "__main__":
    main()
