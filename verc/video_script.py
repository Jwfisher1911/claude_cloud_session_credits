"""VERC lesson video scripts: layouts, checks, and timing estimates.

A video script is a YAML file with one chapter per lesson. Each chapter is a
list of scenes. A scene names a layout, the text shown on screen, and "say",
the narration. A [+] in "say" marks the moment the next on-screen item appears.

LAYOUTS below is the single source for what each layout needs. The generator
builds its instructions to Claude from it, and check() validates scripts
against it, so the two never drift apart.
"""

from __future__ import annotations

import re
from pathlib import Path

import yaml

from verc.style_check import StyleChecker

MARK = "[+]"
WORDS_PER_MINUTE = 145

# Field types: "str" (max chars), "list" of str, "items" list of dicts, "pairs" list of [a, b].
# builds: how many items the layout reveals one at a time. A callable gets the scene.
LAYOUTS: dict[str, dict] = {
    "title": {
        "use": "First scene of every chapter.",
        "fields": {"tag": 30, "headline": 36, "sub": 75},
        "builds": 0,
    },
    "outline": {
        "use": "Chapter map. Module chapter 1 only, second scene.",
        "fields": {"heading": 30, "items": ("list", 32, 3, 6)},
        "builds": lambda s: len(s["items"]),
    },
    "statement": {
        "use": "One idea in a big headline, with a supporting line that appears on cue.",
        "fields": {"tag": 24, "headline": 60, "sub": 110},
        "builds": 1,
    },
    "bignum": {
        "use": "A single number the lesson turns on (3 tasks, 30 minutes, 4 numbers).",
        "fields": {"num": 3, "headline": 24, "sub": 34},
        "builds": 1,
    },
    "list": {
        "use": "Three to six parallel items. Items shaped 'Label: text' get a gold label.",
        "fields": {"tag": 24, "heading": 60, "items": ("list", 55, 3, 6)},
        "builds": lambda s: len(s["items"]),
    },
    "compare": {
        "use": "Exactly three options side by side. Mark the recommended one with hi: true.",
        "fields": {"tag": 24, "cols": ("items", {"label": 18, "text": 70}, 3, 3)},
        "builds": 3,
    },
    "steps": {
        "use": "A numbered procedure. Add a note to two steps at most.",
        "fields": {"tag": 24, "heading": 28, "items": ("items", {"text": 55, "note?": 70}, 3, 7)},
        "builds": lambda s: len(s["items"]),
    },
    "tiles": {
        "use": "Two to four categories with a short definition each.",
        "fields": {"tag": 24, "heading": 30, "tiles": ("items", {"label": 18, "text": 80}, 2, 4)},
        "builds": lambda s: len(s["tiles"]),
    },
    "table": {
        "use": "Two-column table: a short label and its meaning, or a worked example's answers.",
        "fields": {"tag": 60, "heading": 36, "cols": ("list", 16, 2, 2), "rows": ("pairs", (32, 75), 2, 5)},
        "builds": lambda s: len(s["rows"]),
    },
    "example": {
        "use": "The lesson's worked example: a person, their business, two to four facts, and the takeaway.",
        "fields": {"name": 12, "role": 45, "rows": ("items", {"k": 12, "v": 60}, 2, 4), "quote": 62},
        "builds": lambda s: len(s["rows"]) + 1,
    },
    "numbers": {
        "use": "An example built on figures: two to four big numbers and the takeaway.",
        "fields": {"name": 12, "role": 45, "nums": ("pairs", (16, 5), 2, 4), "quote": 62},
        "builds": lambda s: len(s["nums"]) + 1,
    },
    "fieldnote": {
        "use": "The lesson's field note: a headline and two or three short chips.",
        "fields": {"headline": 48, "chips": ("list", 36, 2, 3)},
        "builds": 2,
    },
    "checklist": {
        "use": "The module scorecard, last chapter only, before the end scene.",
        "fields": {"tag": 24, "heading": 24, "items": ("list", 52, 3, 6)},
        "builds": lambda s: len(s["items"]),
    },
    "task": {
        "use": "The lesson's 'Your task today', pointing at a workbook worksheet. Second to last scene of every chapter.",
        "fields": {"worksheet": 50, "text": 60, "checks": ("list", 42, 2, 4), "page?": 40},
        "builds": lambda s: len(s["checks"]),
    },
    "end": {
        "use": "Last scene of every chapter: what comes next.",
        "fields": {"next": 48, "dod?": "bool"},
        "builds": 0,
    },
    # Layouts drawn for one module. Hand-written scripts use them. The generator does not.
    "photo": {
        "use": "Full-bleed photo with a headline. Needs a photo file in output/video/assets.",
        "fields": {"photo": 60, "credit?": 30, "tag": 24, "headline": 48},
        "builds": 1, "special": True,
    },
    "card": {
        "use": "The Daily MET card from Module 1.",
        "fields": {"heading": 24, "first_light": 60, "mets": ("items", {"text": 55, "r?": "bool"}, 3, 3),
                   "below": ("list", 30, 1, 4)},
        "builds": 4, "special": True,
    },
    "grid": {
        "use": "The weekly rhythm grid from Module 1.",
        "fields": {"name": 12, "role": 50, "rows": ("rows", 40, 7, 7)},
        "builds": 4, "special": True,
    },
}

GENERATED_LAYOUTS = [k for k, v in LAYOUTS.items() if not v.get("special")]


def build_count(scene: dict) -> int:
    b = LAYOUTS[scene["layout"]]["builds"]
    return b(scene) if callable(b) else b


def spoken(say: str) -> str:
    """Narration with the build markers removed."""
    return re.sub(r"\s*\[\+\]\s*", " ", str(say)).strip()


def segments(say: str) -> list[str]:
    """Narration split at the [+] markers. Segment k starts build k."""
    return [s.strip() for s in str(say).split(MARK)]


def on_screen_text(scene: dict) -> list[str]:
    out: list[str] = []

    def walk(v):
        if isinstance(v, str):
            out.append(v)
        elif isinstance(v, list):
            for x in v:
                walk(x)
        elif isinstance(v, dict):
            for k, x in v.items():
                if k not in ("say", "layout", "id", "photo", "page", "credit"):
                    walk(x)

    walk(scene)
    return out


def load(path: Path) -> dict:
    return yaml.safe_load(Path(path).read_text(encoding="utf-8"))


def _check_fields(where: str, sc: dict, spec: dict) -> list[str]:
    probs: list[str] = []
    for raw, rule in spec.items():
        key = raw.rstrip("?")
        optional = raw.endswith("?")
        if key not in sc or sc[key] in (None, ""):
            if not optional:
                probs.append(f"{where}: missing field '{key}'")
            continue
        val = sc[key]
        if isinstance(rule, int):
            if len(str(val)) > rule:
                probs.append(f"{where}: '{key}' is {len(str(val))} characters, limit {rule}")
        elif rule == "bool":
            if not isinstance(val, bool):
                probs.append(f"{where}: '{key}' must be true or false")
        else:
            kind, inner, lo, hi = rule
            if not isinstance(val, list):
                probs.append(f"{where}: '{key}' must be a list")
                continue
            if not lo <= len(val) <= hi:
                probs.append(f"{where}: '{key}' has {len(val)} entries, allowed {lo} to {hi}")
            for i, item in enumerate(val, 1):
                tag = f"{where}: {key} #{i}"
                if kind == "list":
                    if not isinstance(item, str):
                        probs.append(f"{tag} must be text")
                    elif len(item) > inner:
                        probs.append(f"{tag} is {len(item)} characters, limit {inner}")
                elif kind == "items":
                    if not isinstance(item, dict):
                        probs.append(f"{tag} must have fields {', '.join(k.rstrip('?') for k in inner)}")
                    else:
                        probs += _check_fields(tag, item, inner)
                elif kind == "pairs":
                    if not (isinstance(item, list) and len(item) == 2):
                        probs.append(f"{tag} must be a pair of two quoted strings, got {item!r}")
                    else:
                        for part, limit in zip(item, inner):
                            if len(str(part)) > limit:
                                probs.append(f"{tag} entry '{part}' is {len(str(part))} characters, limit {limit}")
                elif kind == "rows":
                    if not (isinstance(item, list) and len(item) == 3):
                        probs.append(f"{tag} must be [day, morning, afternoon]")
    return probs


def check(script: dict, allowed: list[str] | None = None, style_rules: Path | None = None) -> list[str]:
    """Return a list of problems. An empty list means the script is ready to render."""
    rules = style_rules or Path(__file__).resolve().parent.parent / "content" / "style_rules.md"
    checker = StyleChecker.from_rules_file(rules)
    probs: list[str] = []
    if not isinstance(script, dict) or not isinstance(script.get("chapters"), list):
        return ["the file must have a top-level 'chapters' list"]
    for key in ("module", "title", "short"):
        if key not in script:
            probs.append(f"missing top-level field '{key}'")
    for ch in script["chapters"]:
        n = ch.get("n", "?")
        scenes = ch.get("scenes") or []
        if not scenes:
            probs.append(f"chapter {n}: no scenes")
            continue
        if scenes[0].get("layout") != "title":
            probs.append(f"chapter {n}: the first scene must use the title layout")
        if scenes[-1].get("layout") != "end":
            probs.append(f"chapter {n}: the last scene must use the end layout")
        ids = [sc.get("id") for sc in scenes]
        if len(set(ids)) != len(ids):
            probs.append(f"chapter {n}: scene ids must be unique within the chapter")
        for sc in scenes:
            where = f"chapter {n} / {sc.get('id', '?')}"
            lay = sc.get("layout")
            if lay not in LAYOUTS:
                probs.append(f"{where}: unknown layout '{lay}'")
                continue
            if allowed is not None and lay not in allowed:
                probs.append(f"{where}: layout '{lay}' is not available here. Use one of: {', '.join(allowed)}")
                continue
            if not sc.get("say"):
                probs.append(f"{where}: missing narration 'say'")
                continue
            probs += _check_fields(where, sc, LAYOUTS[lay]["fields"])
            try:
                want = build_count(sc)
            except (KeyError, TypeError):
                continue
            got = str(sc["say"]).count(MARK)
            if want != got:
                probs.append(f"{where}: the layout shows {want} items one at a time, but the narration has {got} [+] markers")
            for label, text in [("narration", spoken(sc["say"]))] + [("screen text", t) for t in on_screen_text(sc)]:
                for issue in checker.check(text):
                    probs.append(f"{where} {label}: {issue.rule}: \"{issue.excerpt}\"")
    return probs


def stats(script: dict) -> list[tuple[int, str, int, float]]:
    rows = []
    for ch in script["chapters"]:
        words = sum(len(spoken(sc["say"]).split()) for sc in ch["scenes"])
        rows.append((ch["n"], ch["title"], words, words / WORDS_PER_MINUTE))
    return rows


def layout_reference(names: list[str]) -> str:
    """Plain-text reference of the layouts, for the instructions sent to Claude."""
    lines = []
    for name in names:
        spec = LAYOUTS[name]
        b = spec["builds"]
        builds = ("no [+] markers" if b == 0 else f"exactly {b} [+] marker{'s' if b != 1 else ''}") if not callable(b) else \
            {"outline": "one [+] per item", "list": "one [+] per item", "steps": "one [+] per item",
             "tiles": "one [+] per tile", "table": "one [+] per row", "example": "one [+] per row, plus one for the quote",
             "numbers": "one [+] per number, plus one for the quote", "checklist": "one [+] per item",
             "task": "one [+] per check"}[name]
        fields = []
        for raw, rule in spec["fields"].items():
            key, opt = raw.rstrip("?"), raw.endswith("?")
            if isinstance(rule, int):
                desc = f"text, {rule} characters max"
            elif rule == "bool":
                desc = "true or false"
            else:
                kind, inner, lo, hi = rule
                count = f"{lo}" if lo == hi else f"{lo} to {hi}"
                if kind == "list":
                    desc = f"list of {count} texts, {inner} characters max each"
                elif kind == "items":
                    sub = ", ".join(f"{k.rstrip('?')}{' (optional)' if k.endswith('?') else ''} ({v} chars)" if isinstance(v, int)
                                    else f"{k.rstrip('?')} (true/false, optional)" for k, v in inner.items())
                    desc = f"list of {count} entries with fields: {sub}"
                elif kind == "pairs":
                    desc = f'list of {count} pairs, each ["{inner[0]} chars max", "{inner[1]} chars max"], both quoted'
                else:
                    desc = "rows"
            fields.append(f"    {key}{' (optional)' if opt else ''}: {desc}")
        lines.append(f"- {name}: {spec['use']} Narration: {builds}.")
        lines.extend(fields)
    return "\n".join(lines)
