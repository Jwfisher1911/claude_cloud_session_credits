"""Check a Markdown draft against the VERC writing style rules.

The banned word list is read from content/style_rules.md, so editing that
file changes both the instructions Claude gets and the checks run here.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

SETUP_PHRASES = [
    "in conclusion",
    "in closing",
    "in summary",
    "moreover",
    "furthermore",
    "however",
    "hence",
]

# Text inside these markers is exempt from the checks.
VERIFY_RE = re.compile(r"\[VERIFY[^\]]*\]", re.IGNORECASE)
TABLE_SEPARATOR_RE = re.compile(r"^\s*\|?\s*:?-{2,}:?\s*(\|\s*:?-{2,}:?\s*)*\|?\s*$")
HASHTAG_RE = re.compile(r"(?<![\w#&/])#[A-Za-z][\w]*")
NOT_JUST_RE = re.compile(r"\bnot\s+(just|only|merely|simply)\b[^.!?]*\bbut\b", re.IGNORECASE)
EMOJI_RE = re.compile(
    "[\U0001F300-\U0001FAFF\U00002600-\U000026FF\U00002700-\U000027BF\U0001F1E6-\U0001F1FF]"
)
DASH_RES = [
    (re.compile("—"), "em dash"),
    (re.compile(r"\s–\s"), "en dash used as a dash"),
    (re.compile(r"\s--\s"), "double hyphen used as a dash"),
]


@dataclass
class Issue:
    line: int
    rule: str
    excerpt: str

    def describe(self) -> str:
        return f'line {self.line} ({self.rule}): "{self.excerpt}"'


def load_banned_words(style_rules_path: Path) -> list[str]:
    """Read the comma-separated list under the '## Banned words' heading."""
    text = style_rules_path.read_text(encoding="utf-8")
    match = re.search(r"^##\s+Banned words\s*\n+(.+?)(?:\n\s*\n|\n##|\Z)", text, re.M | re.S)
    if not match:
        return []
    raw = " ".join(match.group(1).split())
    return [w.strip().lower() for w in raw.split(",") if w.strip()]


def _phrase_pattern(phrase: str) -> re.Pattern[str]:
    parts = [re.escape(p) for p in phrase.split()]
    return re.compile(r"(?<![\w-])" + r"\s+".join(parts) + r"(?![\w-])", re.IGNORECASE)


def _excerpt(line: str, start: int, end: int, width: int = 45) -> str:
    left = max(0, start - width)
    right = min(len(line), end + width)
    snippet = line[left:right].strip()
    if left > 0:
        snippet = "..." + snippet
    if right < len(line):
        snippet = snippet + "..."
    return snippet


class StyleChecker:
    def __init__(self, banned_words: list[str]):
        self.word_patterns = [(w, _phrase_pattern(w)) for w in banned_words]
        self.setup_patterns = [(p, _phrase_pattern(p)) for p in SETUP_PHRASES]

    @classmethod
    def from_rules_file(cls, path: Path) -> "StyleChecker":
        return cls(load_banned_words(path))

    def check(self, markdown: str) -> list[Issue]:
        issues: list[Issue] = []
        for number, raw_line in enumerate(markdown.splitlines(), start=1):
            if TABLE_SEPARATOR_RE.match(raw_line):
                continue
            # Blank out VERIFY markers so their wording is not flagged.
            line = VERIFY_RE.sub(lambda m: " " * len(m.group(0)), raw_line)
            # Markdown heading marks are not hashtags.
            body = re.sub(r"^\s*#{1,6}\s", lambda m: " " * len(m.group(0)), line)

            for pattern, label in DASH_RES:
                for m in pattern.finditer(body):
                    issues.append(Issue(number, label, _excerpt(raw_line, m.start(), m.end())))
            for m in re.finditer(";", body):
                issues.append(Issue(number, "semicolon", _excerpt(raw_line, m.start(), m.end())))
            for m in HASHTAG_RE.finditer(body):
                issues.append(Issue(number, "hashtag", _excerpt(raw_line, m.start(), m.end())))
            for m in EMOJI_RE.finditer(body):
                issues.append(Issue(number, "emoji", _excerpt(raw_line, m.start(), m.end())))
            for m in NOT_JUST_RE.finditer(body):
                issues.append(Issue(number, '"not just X but Y"', _excerpt(raw_line, m.start(), m.end())))
            for phrase, pattern in self.setup_patterns:
                for m in pattern.finditer(body):
                    issues.append(Issue(number, f'setup phrase "{phrase}"', _excerpt(raw_line, m.start(), m.end())))
            for word, pattern in self.word_patterns:
                if word in SETUP_PHRASES:
                    continue
                for m in pattern.finditer(body):
                    issues.append(Issue(number, f'banned word "{word}"', _excerpt(raw_line, m.start(), m.end())))
        return issues


def find_verify_markers(markdown: str) -> list[str]:
    return [m.group(0) for m in VERIFY_RE.finditer(markdown)]


def summarize(issues: list[Issue]) -> str:
    counts: dict[str, int] = {}
    for issue in issues:
        counts[issue.rule] = counts.get(issue.rule, 0) + 1
    return ", ".join(f"{rule} x{n}" for rule, n in sorted(counts.items(), key=lambda kv: -kv[1]))
