"""Build the prompts sent to Claude.

The system prompt holds everything shared by every request: the brand guide,
the style rules, the format rules, the full course outline, and the approved
source files. It is marked for prompt caching, so after the first request the
API reads it from cache at a reduced rate instead of charging full price.
"""

from __future__ import annotations

from pathlib import Path

FORMAT_RULES = """\
Write in Markdown using only these elements. A script converts the Markdown into a Word document.
- "# " once, for the document title on the first line.
- "## " for main sections, "### " for subsections. Never go deeper than "#### ".
- Plain paragraphs separated by a blank line.
- "- " for bullets. Indent two spaces for a second level.
- "1. " for numbered steps.
- "- [ ] " for checklist items the reader ticks off.
- "> " for a shaded callout box. Start each callout with a bold label, for example "> **Field note:** ...".
- Pipe tables with a header row and a separator row. Keep tables to five columns or fewer so they print on a portrait page. For fill-in tables, add empty rows ("|  |  |  |") for the reader to write in.
- "[[LINES 3]]" on its own line for three ruled lines of handwriting space. Use any number from 1 to 10.
- **bold** and *italic* inside text.
- [VERIFY: what to check] wherever a fact, rule, price, deadline, or menu name is not in the approved sources.
Never use HTML, code blocks, images, links, emojis, or footnotes. Do not add a preamble or a closing note. Output the document only."""


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8").strip()


def curriculum_overview(curriculum: dict) -> str:
    lines = []
    for track in curriculum["tracks"]:
        lines.append(f"Track: {track['title']} ({len(track['modules'])} modules)")
        for n, module in enumerate(track["modules"], start=1):
            lines.append(f"  Module {n}: {module['title']}")
            lines.append(f"    Goal: {module['goal']}")
            for lesson in module.get("lessons", []):
                lines.append(f"    - Lesson topic: {lesson}")
            for sheet in module.get("worksheets", []):
                lines.append(f"    - Worksheet: {sheet}")
    return "\n".join(lines)


def build_system_prompt(content_dir: Path, curriculum: dict) -> str:
    source_paths = sorted({s for t in curriculum["tracks"] for s in t.get("sources", [])})
    sources = "\n\n".join(
        f'<source name="{Path(s).name}">\n{_read(content_dir / s)}\n</source>' for s in source_paths
    )
    program = curriculum["program"]
    return f"""You are the senior curriculum writer for {program['name']} ({program['short_name']}). You write lesson guides and printable workbooks for veterans, military spouses, and service-disabled veteran entrepreneurs. Each document you write becomes a draft the founder reviews before publishing.

<brand_guide>
{_read(content_dir / 'brand.md')}
</brand_guide>

<style_rules>
{_read(content_dir / 'style_rules.md')}
</style_rules>

<format_rules>
{FORMAT_RULES}
</format_rules>

<course_outline>
The full course, so each module builds on earlier ones and avoids repeating them.
{curriculum_overview(curriculum)}
</course_outline>

<approved_sources>
These files are the only approved source for program rules, eligibility, deadlines, and figures. Do not state a program rule from memory. If a needed fact is missing here, write a [VERIFY: ...] marker instead of guessing.
{sources or '(none)'}
</approved_sources>"""


def _module_header(track: dict, module: dict, number: int) -> str:
    lines = [
        f'Module {number} of {len(track["modules"])} in the "{track["title"]}" track: "{module["title"]}".',
        f"Module goal: {module['goal']}",
    ]
    if module.get("notes"):
        lines.append(f"Founder notes: {module['notes']}")
    if track.get("sources"):
        lines.append(
            "This track covers a government program. Every program rule must come from the approved sources. "
            "Mark anything else with a VERIFY marker, and remind readers that SBA makes every certification decision."
        )
    return "\n".join(lines)


def lesson_prompt(track: dict, module: dict, number: int, lesson_words: int) -> str:
    topics = "\n".join(f"{i}. {t}" for i, t in enumerate(module.get("lessons", []), start=1))
    return f"""Write the LESSON GUIDE for {_module_header(track, module, number)}

Lessons to cover, in this order:
{topics}

Length: about {lesson_words} words.

Use this structure:
# {module['title']}
## What you will be able to do
Three to five outcomes as bullets.
## Lesson 1: <short title>
Teach the idea in plain words. Give numbered steps. Add one worked example from a small service business, labeled "**Example:**". Add one callout starting "> **Field note:**" with a practical tip. End the lesson with "**Your task today:**" and one concrete action.
(Repeat for every lesson.)
## Key terms
Bullets in the form "**Term:** definition", written for military spouses and civilians.
## Before the next module
A checklist ("- [ ] ") of three to six items."""


def workbook_prompt(track: dict, module: dict, number: int, lesson_markdown: str | None) -> str:
    sheets = "\n".join(f"{i}. {s}" for i, s in enumerate(module.get("worksheets", []), start=1))
    lesson_block = (
        f"The workbook pairs with this lesson guide. Use the same terms, steps, and examples.\n<lesson_guide>\n{lesson_markdown}\n</lesson_guide>\n\n"
        if lesson_markdown
        else ""
    )
    return f"""Write the WORKBOOK for {_module_header(track, module, number)}

{lesson_block}Worksheets to include, in this order:
{sheets}

Use this structure:
# {module['title']} Workbook
## How to use this workbook
Three to five bullets. Include a line for the reader's name and date.
## Worksheet 1: <name>
One sentence on the purpose. Numbered instructions. Then the worksheet itself: fill-in tables with empty rows, checklists, and [[LINES n]] blocks for written answers. A filled example row is fine if its first cell starts with "Example". Each worksheet prints on its own page.
(Repeat for every worksheet.)
## Module scorecard
A short checklist ("- [ ] ") the reader completes when the module is done.

Design for printing and handwriting: generous blank space, short instructions, no more than five table columns."""


def fix_prompt(issue_lines: list[str]) -> str:
    listed = "\n".join(f"- {line}" for line in issue_lines)
    return f"""Revise the document you just wrote. It breaks these style rules:
{listed}

Fix every listed issue and any others like them. Rewrite each affected sentence so it reads naturally. Keep the content, structure, tables, and format rules unchanged. Return the complete revised document only."""
