"""Offline smoke test. Runs the full generator with a fake Claude client.

No API key needed and no credits spent:
    python3 tests/smoke_test.py
"""

from __future__ import annotations

import sys
import tempfile
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import generate  # noqa: E402
from verc.style_check import StyleChecker  # noqa: E402

SAMPLES = ROOT / "content" / "samples"
BAD_DRAFT = (SAMPLES / "layout_preview_lesson.md").read_text().replace(
    "Your first hour sets the day.", "You can actually set the day — however, it is very hard; really."
)


class FakeStream:
    def __init__(self, text: str):
        self.text = text
        self.text_stream = iter([text[i : i + 200] for i in range(0, len(text), 200)])

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def get_final_message(self):
        usage = SimpleNamespace(input_tokens=1200, output_tokens=len(self.text) // 4,
                                cache_creation_input_tokens=0, cache_read_input_tokens=5000)
        return SimpleNamespace(content=[SimpleNamespace(type="text", text=self.text)],
                               usage=usage, stop_reason="end_turn")


class FakeMessages:
    def __init__(self):
        self.calls = []

    def stream(self, **kwargs):
        self.calls.append(kwargs)
        last = kwargs["messages"][-1]["content"]
        if "Revise the document" in last:
            return FakeStream((SAMPLES / "layout_preview_lesson.md").read_text())
        if "WORKBOOK" in last:
            return FakeStream("```markdown\n" + (SAMPLES / "layout_preview_workbook.md").read_text() + "\n```")
        return FakeStream(BAD_DRAFT)


def main() -> None:
    checker = StyleChecker.from_rules_file(ROOT / "content" / "style_rules.md")
    for sample in SAMPLES.glob("*.md"):
        issues = checker.check(sample.read_text())
        assert not issues, f"{sample.name} breaks style rules: {[i.describe() for i in issues]}"
    bad = checker.check(BAD_DRAFT)
    rules = {i.rule for i in bad}
    for expected in ('banned word "can"', "em dash", "semicolon", 'setup phrase "however"', 'banned word "very"'):
        assert expected in rules, f"checker missed {expected}: {rules}"

    fake = SimpleNamespace(messages=FakeMessages())
    with tempfile.TemporaryDirectory() as tmp:
        generate.OUTPUT = Path(tmp) / "output"
        generate.ROOT = Path(tmp)
        generate.make_client = lambda: fake
        sys.argv = ["generate.py", "--module", "battle-rhythm"]
        generate.main()

        calls = fake.messages.calls
        assert len(calls) == 3, f"expected lesson + revision + workbook, got {len(calls)} calls"
        assert calls[0]["system"][0]["cache_control"] == {"type": "ephemeral"}
        assert "<lesson_guide>" in calls[2]["messages"][0]["content"], "workbook prompt is missing the lesson"
        word = generate.OUTPUT / "word" / "core"
        for name in ("01-battle-rhythm-lesson.docx", "01-battle-rhythm-workbook.docx"):
            assert (word / name).exists(), f"missing {name}"
        saved = (generate.OUTPUT / "markdown" / "core" / "01-battle-rhythm-workbook.md").read_text()
        assert not saved.startswith("```"), "code fence was not stripped"
        assert list((generate.OUTPUT / "reports").glob("run-*.md")), "no report written"

        # A second run skips finished documents.
        fake.messages.calls.clear()
        generate.main()
        assert not fake.messages.calls, "second run should skip existing documents"

    print("\nSmoke test passed.")


if __name__ == "__main__":
    main()
