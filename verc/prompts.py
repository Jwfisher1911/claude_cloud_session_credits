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


# ----------------------------------------------------------------------------
# Lesson video scripts
# ----------------------------------------------------------------------------
def video_system_block(layout_reference: str, example_yaml: str) -> str:
    """Shared instructions for video scripts. Sent as a second cached system block."""
    return f"""<video_scripts>
Some requests ask for a LESSON VIDEO SCRIPT instead of a Markdown document. For those requests, ignore the Markdown format rules above and return one YAML document in the format below. Every other rule still applies: the brand guide, the style rules, the banned words, and the approved sources.

How the video works. Each lesson in the guide becomes one chapter of 2 to 3 minutes. A chapter is a list of scenes shown at 1920 x 1080 with the narration read aloud and captioned. Each scene uses one layout. Most layouts reveal their items one at a time, and a [+] in the narration marks the moment the next item appears. The number of [+] markers in a scene must equal the number of items that layout reveals, exactly.

Writing the narration ("say"):
- Write for the ear. Short sentences. One idea per sentence. Address the viewer as "you".
- Teach the same steps, terms, and examples as the lesson guide. Do not add new facts, figures, or program rules.
- Each chapter: 300 to 470 words of narration in total.
- Open each chapter with its title scene. End it with a task scene that sends the viewer to the matching workbook worksheet by number and name, then an end scene naming the next chapter. Chapter 1 has an outline scene second: a map of every chapter in the module.
- Give each chapter an "n" (1, 2, 3...) and a short "title" of 34 characters or fewer, taken from the lesson's heading in the guide.
- Use each lesson's example and field note. Keep the example people and their details from the guide.
- Put each [+] right before the words that match the item that appears.
- Never put a [VERIFY] marker in a video script. If the guide marks a fact with VERIFY, leave that fact out of the video.

On-screen text:
- Screen text is shorter than the narration. Headlines are statements, not questions, unless the narration asks the question.
- Respect every character limit. Text past a limit runs off the frame.
- The style rules apply to screen text too.

YAML rules:
- Return the YAML document only. No code fences, no comments, no text before or after.
- Write every "say" value as a folded block: say: >- on its own line, then the narration indented on the following lines.
- Wrap in double quotes any text value that contains a colon, a quote mark, or starts with a number.
- Write pairs as ["first", "second"] with both parts in double quotes.
- Scene ids: short, lowercase, hyphenated, unique within the chapter.

Layouts available:
{layout_reference}

Here is a complete, approved script for Module 1 in the core track. Match its structure, pacing, tone, and YAML formatting. It uses three layouts drawn for Module 1 only (photo, card, grid). Do not use those three.
<example_script>
{example_yaml}
</example_script>
</video_scripts>"""


def video_prompt(track: dict, module: dict, number: int, lesson_md: str, workbook_md: str | None,
                 next_title: str, short: str) -> str:
    import json

    chapters = "\n".join(f"Chapter {i}: {t}" for i, t in enumerate(module.get("lessons", []), start=1))
    workbook_block = f"<workbook>\n{workbook_md}\n</workbook>\n\n" if workbook_md else ""
    return f"""Write the LESSON VIDEO SCRIPT for {_module_header(track, module, number)}

Chapters, one per lesson in the guide, in this order:
{chapters}

Use these top-level fields exactly:
module: {number}
track: {track['id']}
title: {json.dumps(module['title'])}
short: {json.dumps(short)}

The last chapter's end scene names the next module: "{next_title}".

<lesson_guide>
{lesson_md}
</lesson_guide>

{workbook_block}Return the YAML document only."""


def video_fix_prompt(problems: list[str]) -> str:
    listed = "\n".join(f"- {p}" for p in problems)
    return f"""The script you just wrote fails these checks:
{listed}

Fix every listed problem. Shorten text that is over its limit, make the [+] count match each layout, and rewrite sentences that break the style rules. Keep everything else the same. Return the complete corrected YAML document only."""
