#!/usr/bin/env python3
"""VERC course generator.

Drafts VERC lesson guides and workbooks with the Claude API, checks each draft
against the VERC style rules, and saves Word documents to output/word/.

Common commands (run from this folder):
    python3 generate.py --list                     show every module and its id
    python3 generate.py --kind video               write a lesson video script for every module with a lesson guide
    python3 generate.py --dry-run                  show what would be written, spend nothing
    python3 generate.py --preview                  build sample Word files to check the layout, spend nothing
    python3 generate.py --module battle-rhythm     write one module (lesson + workbook)
    python3 generate.py --track core               write every core module
    python3 generate.py                            write everything not written yet
    python3 generate.py --rebuild-word             rebuild Word files from saved Markdown, spend nothing
"""

from __future__ import annotations

import argparse
import datetime as dt
import os
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path

try:
    import yaml

    from verc.prompts import (build_system_prompt, fix_prompt, lesson_prompt, video_fix_prompt,
                              video_prompt, video_system_block, workbook_prompt)
    from verc.style_check import StyleChecker, find_verify_markers, summarize
    from verc import video_script
    from verc.worksheet_pages import workbook_pages
    from verc.word_builder import DocInfo, markdown_to_docx
except ModuleNotFoundError as missing:
    sys.exit(
        f"Missing Python package: {missing.name}\n\n"
        "Install the packages first (README step 2). From this folder, run:\n"
        "    python3 -m venv .venv\n"
        "    source .venv/bin/activate\n"
        "    pip install -r requirements.txt\n\n"
        "Already installed them? Activate them in this Terminal window first:\n"
        "    source .venv/bin/activate"
    )

ROOT = Path(__file__).resolve().parent
CONTENT = ROOT / "content"
OUTPUT = ROOT / "output"
KINDS = ("lesson", "workbook")
VIDEO = "video"
# Set from curriculum.yaml "effort" when present. None sends no effort setting (the model default).
EFFORT = None
NEXT_STEP_TITLE = "Next step: your free VetCert score"


# ----------------------------------------------------------------------------
# Plan
# ----------------------------------------------------------------------------
@dataclass
class Job:
    track: dict
    module: dict
    number: int
    kind: str  # "lesson", "workbook", or "video"

    @property
    def stem(self) -> str:
        return f"{self.number:02d}-{self.module['id']}-{self.kind}"

    @property
    def md_path(self) -> Path:
        return OUTPUT / "markdown" / self.track["id"] / f"{self.stem}.md"

    @property
    def docx_path(self) -> Path:
        return OUTPUT / "word" / self.track["id"] / f"{self.stem}.docx"

    @property
    def lesson_md_path(self) -> Path:
        return OUTPUT / "markdown" / self.track["id"] / f"{self.number:02d}-{self.module['id']}-lesson.md"

    @property
    def workbook_md_path(self) -> Path:
        return OUTPUT / "markdown" / self.track["id"] / f"{self.number:02d}-{self.module['id']}-workbook.md"

    @property
    def video_path(self) -> Path:
        return OUTPUT / "video" / "scripts" / self.track["id"] / f"{self.stem}.yaml"

    @property
    def approved_video_path(self) -> Path:
        """A hand-written script kept in the repo. The generator uses it instead of writing one."""
        return ROOT / "video" / "scripts" / self.track["id"] / f"{self.number:02d}-{self.module['id']}.yaml"

    @property
    def out_path(self) -> Path:
        return self.video_path if self.kind == VIDEO else self.docx_path

    @property
    def label(self) -> str:
        return f"{self.track['id']} / {self.module['id']} / {self.kind}"


@dataclass
class Totals:
    calls: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    cache_write: int = 0
    cache_read: int = 0

    def add(self, usage) -> None:
        self.calls += 1
        self.input_tokens += usage.input_tokens or 0
        self.output_tokens += usage.output_tokens or 0
        self.cache_write += getattr(usage, "cache_creation_input_tokens", 0) or 0
        self.cache_read += getattr(usage, "cache_read_input_tokens", 0) or 0

    def line(self) -> str:
        return (
            f"{self.calls} API calls | input {self.input_tokens:,} | output {self.output_tokens:,} | "
            f"cache write {self.cache_write:,} | cache read {self.cache_read:,} tokens"
        )


@dataclass
class Result:
    job: Job
    words: int
    issues_left: list = field(default_factory=list)
    verify: list = field(default_factory=list)
    truncated: bool = False
    revised: bool = False
    note: str = ""


def load_curriculum() -> dict:
    with open(CONTENT / "curriculum.yaml", encoding="utf-8") as f:
        return yaml.safe_load(f)


def plan_jobs(curriculum: dict, args) -> list[Job]:
    tracks = [t for t in curriculum["tracks"] if args.track in (None, "all", t["id"])]
    all_ids = {m["id"] for t in curriculum["tracks"] for m in t["modules"]}
    unknown = [m for m in (args.module or []) if m not in all_ids]
    if unknown:
        sys.exit(f"Unknown module id: {', '.join(unknown)}. Run with --list to see valid ids.")
    kinds = KINDS if args.kind == "both" else (args.kind,)
    jobs = []
    for track in tracks:
        for number, module in enumerate(track["modules"], start=1):
            if args.module and module["id"] not in args.module:
                continue
            for kind in kinds:
                jobs.append(Job(track, module, number, kind))
    return jobs


def doc_info(curriculum: dict, job: Job) -> DocInfo:
    program, settings = curriculum["program"], curriculum.get("settings", {})
    workbook = job.kind == "workbook"
    return DocInfo(
        program_name=program["name"],
        doc_type="Workbook" if workbook else "Lesson Guide",
        title=job.module["title"],
        subtitle=f"Module {job.number} of {len(job.track['modules'])}  |  {job.track['title']}",
        goal=job.module.get("goal", ""),
        disclaimer=program.get("disclaimer", ""),
        legal_line=program.get("legal_line", ""),
        website=program.get("website", ""),
        colors=settings.get("colors", {}),
        font=settings.get("font", "Calibri"),
        break_before_h2=workbook,
    )


# ----------------------------------------------------------------------------
# Claude API
# ----------------------------------------------------------------------------
def make_client():
    try:
        from dotenv import load_dotenv

        load_dotenv(ROOT / ".env")
    except ImportError:
        pass
    if not os.environ.get("ANTHROPIC_API_KEY"):
        sys.exit(
            "No API key found. Copy .env.example to .env and paste your Claude Console API key into it.\n"
            "See README.md, step 3."
        )
    import anthropic

    return anthropic.Anthropic(max_retries=4)


def stream_text(client, model: str, max_tokens: int, system_blocks: list, messages: list, label: str):
    """Send one request, show live progress, and return (text, usage, stop_reason).

    Claude thinks before it writes. Thinking counts toward max_tokens but is not
    shown, so the word count starts once the writing starts.
    """
    chars, shown = 0, 0
    print(f"    {label}: thinking...", end="", flush=True)
    extra = {"extra_body": {"output_config": {"effort": EFFORT}}} if EFFORT else {}
    with client.messages.stream(model=model, max_tokens=max_tokens, system=system_blocks, messages=messages, **extra) as stream:
        for chunk in stream.text_stream:
            chars += len(chunk)
            if chars - shown >= 300:
                shown = chars
                print(f"\r    {label}: about {chars // 6:,} words", end="", flush=True)
        final = stream.get_final_message()
    print(f"\r    {label}: done, about {chars // 6:,} words      ")
    text = "".join(block.text for block in final.content if block.type == "text")
    return clean_markdown(text), final.usage, final.stop_reason


def clean_markdown(text: str) -> str:
    text = text.strip()
    if text.startswith("```"):
        text = text.split("\n", 1)[1] if "\n" in text else ""
        if text.rstrip().endswith("```"):
            text = text.rstrip()[:-3]
    return text.strip() + "\n"


def run_job(client, curriculum, system_blocks, checker, job: Job, totals: Totals, model: str, auto_fix: bool) -> Result:
    settings = curriculum.get("settings", {})
    max_tokens = int(settings.get("max_tokens", 16000))
    if job.kind == "lesson":
        prompt = lesson_prompt(job.track, job.module, job.number, int(settings.get("lesson_words", 2500)))
    else:
        lesson_md = job.lesson_md_path.read_text(encoding="utf-8") if job.lesson_md_path.exists() else None
        if lesson_md is None:
            print("    note: no lesson guide found for this module, writing the workbook on its own")
        prompt = workbook_prompt(job.track, job.module, job.number, lesson_md)

    messages = [{"role": "user", "content": prompt}]
    text, usage, stop = stream_text(client, model, max_tokens, system_blocks, messages, "drafting")
    totals.add(usage)
    print(f"    tokens: input {usage.input_tokens:,}, output {usage.output_tokens:,}, "
          f"cache read {getattr(usage, 'cache_read_input_tokens', 0) or 0:,}")
    truncated = stop == "max_tokens"
    issues = checker.check(text)
    revised = False

    if issues and auto_fix and not truncated:
        print(f"    style check: {len(issues)} issues ({summarize(issues)}). Sending one revision request.")
        fix_messages = messages + [
            {"role": "assistant", "content": text.strip()},
            {"role": "user", "content": fix_prompt([i.describe() for i in issues[:80]])},
        ]
        new_text, usage2, stop2 = stream_text(client, model, max_tokens, system_blocks, fix_messages, "revising")
        totals.add(usage2)
        new_issues = checker.check(new_text)
        if stop2 != "max_tokens" and len(new_issues) <= len(issues):
            text, issues, revised = new_text, new_issues, True
        else:
            print("    revision was not better, keeping the first draft")
    elif issues:
        print(f"    style check: {len(issues)} issues left ({summarize(issues)}).")
    else:
        print("    style check: clean")

    if truncated:
        print("    WARNING: the draft hit the max_tokens limit and is cut off. Raise max_tokens in curriculum.yaml.")

    job.md_path.parent.mkdir(parents=True, exist_ok=True)
    job.md_path.write_text(text, encoding="utf-8")
    markdown_to_docx(text, doc_info(curriculum, job), job.docx_path)
    print(f"    saved {job.docx_path.relative_to(ROOT)}")
    return Result(job, len(text.split()), issues, find_verify_markers(text), truncated, revised)


# ----------------------------------------------------------------------------
# Lesson video scripts
# ----------------------------------------------------------------------------
def video_instructions() -> str:
    example = ROOT / "video" / "scripts" / "core" / "01-battle-rhythm.yaml"
    text = example.read_text(encoding="utf-8")
    text = "\n".join(l for l in text.splitlines() if not l.startswith("#")).strip()
    return video_system_block(video_script.layout_reference(video_script.GENERATED_LAYOUTS), text)


def next_module_title(job: Job) -> str:
    mods = job.track["modules"]
    if job.number < len(mods):
        nxt = mods[job.number]
        return f"Module {job.number + 1} · {nxt.get('short') or nxt['title']}"
    return NEXT_STEP_TITLE


def worksheet_problems(script: dict, workbook_md: str | None) -> list[str]:
    """Each task scene must point at a worksheet the workbook has."""
    if not workbook_md or not isinstance(script, dict):
        return []
    have = sorted(int(n) for n in workbook_pages(workbook_md))
    probs = []
    for ch in script.get("chapters") or []:
        for sc in ch.get("scenes") or []:
            if sc.get("layout") == "task":
                m = re.search(r"Worksheet\s+(\d+)", str(sc.get("worksheet", "")), re.I)
                if not m or int(m.group(1)) not in have:
                    probs.append(f"chapter {ch.get('n')} / {sc.get('id')}: 'worksheet' must name one of the workbook's "
                                 f"worksheets ({', '.join(f'Worksheet {n}' for n in have)}), as 'Worksheet N · Name'")
    return probs


def parse_and_check(text: str, job: Job) -> tuple[dict | None, list[str]]:
    try:
        script = yaml.safe_load(text)
    except yaml.YAMLError as err:
        return None, [f"the YAML does not parse: {str(err).splitlines()[0]}"]
    problems = video_script.check(script, allowed=video_script.GENERATED_LAYOUTS)
    if isinstance(script, dict):
        want = {"module": job.number, "track": job.track["id"]}
        for k, v in want.items():
            if script.get(k) != v:
                problems.append(f"top-level '{k}' must be {v}")
        n_lessons = len(job.module.get("lessons", []))
        if len(script.get("chapters") or []) != n_lessons:
            problems.append(f"the script needs {n_lessons} chapters, one per lesson")
        for ch in script.get("chapters") or []:
            if len(str(ch.get("title", ""))) > 34:
                problems.append(f"chapter {ch.get('n')}: title is over 34 characters")
        wb = job.workbook_md_path.read_text(encoding="utf-8") if job.workbook_md_path.exists() else None
        problems += worksheet_problems(script, wb)
    return script, problems


def run_video_job(client, curriculum, system_blocks, job: Job, totals: Totals, model: str, auto_fix: bool):
    job.video_path.parent.mkdir(parents=True, exist_ok=True)
    if job.approved_video_path.exists():
        text = job.approved_video_path.read_text(encoding="utf-8")
        job.video_path.write_text(text, encoding="utf-8")
        script, problems = parse_and_check(text, job)
        words = sum(len(video_script.spoken(sc["say"]).split()) for ch in script["chapters"] for sc in ch["scenes"])
        print(f"    using the approved script in {job.approved_video_path.relative_to(ROOT)}, no API call")
        return Result(job, words, [], [], note="Approved hand-written script, copied")
    if not job.lesson_md_path.exists():
        print(f"    skipped: write the lesson guide first (python3 generate.py --module {job.module['id']} --kind lesson)")
        return None

    settings = curriculum.get("settings", {})
    max_tokens = int(settings.get("video_max_tokens", 48000))
    lesson_md = job.lesson_md_path.read_text(encoding="utf-8")
    workbook_md = job.workbook_md_path.read_text(encoding="utf-8") if job.workbook_md_path.exists() else None
    short = job.module.get("short") or " ".join(job.module["title"].split(":")[0].split()[:3])
    prompt = video_prompt(job.track, job.module, job.number, lesson_md, workbook_md, next_module_title(job), short)
    messages = [{"role": "user", "content": prompt}]
    text, usage, stop = stream_text(client, model, max_tokens, system_blocks, messages, "writing script")
    totals.add(usage)
    print(f"    tokens: input {usage.input_tokens:,}, output {usage.output_tokens:,}, "
          f"cache read {getattr(usage, 'cache_read_input_tokens', 0) or 0:,}")
    truncated = stop == "max_tokens"
    script, problems = parse_and_check(text, job)
    revised = False

    if problems and auto_fix and not truncated:
        print(f"    checks: {len(problems)} problems. Sending one revision request.")
        fix_messages = messages + [
            {"role": "assistant", "content": text.strip()},
            {"role": "user", "content": video_fix_prompt(problems[:80])},
        ]
        new_text, usage2, stop2 = stream_text(client, model, max_tokens, system_blocks, fix_messages, "revising")
        totals.add(usage2)
        new_script, new_problems = parse_and_check(new_text, job)
        if stop2 != "max_tokens" and new_script is not None and len(new_problems) <= len(problems):
            text, script, problems, revised = new_text, new_script, new_problems, True
        else:
            print("    revision was not better, keeping the first script")
    print(f"    checks: {'clean' if not problems else str(len(problems)) + ' problems left, see the report'}")
    if truncated:
        print("    WARNING: the script hit the token limit and is cut off. Raise video_max_tokens in curriculum.yaml,")
        print(f"    then rerun with --force: python3 generate.py --module {job.module['id']} --kind video --force")

    job.video_path.write_text(text, encoding="utf-8")
    print(f"    saved {job.video_path.relative_to(ROOT)}")
    words = 0
    if script and isinstance(script.get("chapters"), list):
        words = sum(len(video_script.spoken(sc.get("say", "")).split())
                    for ch in script["chapters"] for sc in (ch.get("scenes") or []))
    return Result(job, words, problems, find_verify_markers(text), truncated, revised)


# ----------------------------------------------------------------------------
# Reports and commands
# ----------------------------------------------------------------------------
def write_report(results: list[Result], totals: Totals, model: str) -> Path:
    stamp = dt.datetime.now()
    path = OUTPUT / "reports" / f"run-{stamp:%Y%m%d-%H%M}.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = [f"# Generator run {stamp:%B %d, %Y %H:%M}", "", f"Model: {model}", f"Usage: {totals.line()}", ""]
    for r in results:
        lines.append(f"## {r.job.out_path.relative_to(ROOT)}")
        if r.note:
            lines.append(f"- {r.note}")
        lines.append(f"- About {r.words:,} words{', revised once' if r.revised else ''}")
        if r.truncated:
            lines.append("- CUT OFF: hit max_tokens. Raise max_tokens and rerun with --force.")
        lines.append(f"- {'Checks failed' if r.job.kind == VIDEO else 'Style issues left'}: {len(r.issues_left)}")
        lines.extend(f"  - {i.describe() if hasattr(i, 'describe') else i}" for i in r.issues_left[:25])
        lines.append(f"- VERIFY notes to check: {len(r.verify)}")
        lines.extend(f"  - {v}" for v in r.verify)
        lines.append("")
    path.write_text("\n".join(lines), encoding="utf-8")
    return path


def cmd_list(curriculum: dict) -> None:
    for track in curriculum["tracks"]:
        print(f"\n{track['title']}  (--track {track['id']})")
        for n, module in enumerate(track["modules"], start=1):
            print(f"  {n:>2}. {module['id']:<18} {module['title']}")
    print()


def cmd_preview(curriculum: dict) -> None:
    samples = CONTENT / "samples"
    track = curriculum["tracks"][0]
    module = track["modules"][0]
    for kind in KINDS:
        job = Job(track, module, 1, kind)
        md = (samples / f"layout_preview_{kind}.md").read_text(encoding="utf-8")
        out = OUTPUT / "word" / f"_layout-preview-{kind}.docx"
        markdown_to_docx(md, doc_info(curriculum, job), out)
        print(f"Saved {out.relative_to(ROOT)}")


def cmd_rebuild(curriculum: dict, jobs: list[Job]) -> None:
    built = 0
    for job in jobs:
        if job.md_path.exists():
            markdown_to_docx(job.md_path.read_text(encoding="utf-8"), doc_info(curriculum, job), job.docx_path)
            print(f"Rebuilt {job.docx_path.relative_to(ROOT)}")
            built += 1
    print(f"{built} Word files rebuilt. No API calls made.")


def cmd_dry_run(jobs: list[Job], system_prompt: str, model: str, force: bool, auto_fix: bool) -> None:
    todo = [j for j in jobs if force or not j.out_path.exists()]
    print(f"\nModel: {model}")
    print(f"Shared instructions: about {len(system_prompt) // 4:,} tokens (cached after the first call)\n")
    for job in jobs:
        status = "write" if job in todo else "skip, already written"
        if job in todo and job.kind == VIDEO:
            if job.approved_video_path.exists():
                status = "copy the approved script, no API call"
            elif not job.lesson_md_path.exists():
                status = "skip, write the lesson guide first"
        print(f"  {job.label:<45} {status}")
    calls = [j for j in todo if not (j.kind == VIDEO and (j.approved_video_path.exists() or not j.lesson_md_path.exists()))]
    if any(j.kind == VIDEO for j in calls):
        print(f"\nVideo script instructions: about {len(video_instructions()) // 4:,} more tokens (also cached)")
    extra = f", plus up to {len(calls)} revisions" if auto_fix and calls else ""
    print(f"\n{len(calls)} documents to write: {len(calls)} API calls{extra}. Nothing was sent.\n")


def main() -> None:
    parser = argparse.ArgumentParser(description="Draft VERC lesson guides and workbooks with Claude.")
    parser.add_argument("--track", choices=["core", "vetcert", "all"], help="limit to one track")
    parser.add_argument("--module", action="append", help="module id to write (repeat for more); see --list")
    parser.add_argument("--kind", choices=["lesson", "workbook", "both", "video"], default="both",
                        help="both = lesson guide and workbook; video = lesson video script")
    parser.add_argument("--model", help="override the model in curriculum.yaml")
    parser.add_argument("--force", action="store_true", help="rewrite documents that already exist")
    parser.add_argument("--no-fix", action="store_true", help="skip the automatic style revision")
    parser.add_argument("--dry-run", action="store_true", help="show the plan without calling the API")
    parser.add_argument("--list", action="store_true", help="list tracks and module ids")
    parser.add_argument("--preview", action="store_true", help="build sample Word files to check the layout")
    parser.add_argument("--rebuild-word", action="store_true", help="rebuild Word files from saved Markdown")
    args = parser.parse_args()

    curriculum = load_curriculum()
    settings = curriculum.get("settings", {})
    model = args.model or settings.get("model", "claude-opus-5-5")
    global EFFORT
    EFFORT = settings.get("effort") or None
    auto_fix = bool(settings.get("auto_fix", True)) and not args.no_fix

    if args.list:
        return cmd_list(curriculum)
    if args.preview:
        return cmd_preview(curriculum)
    jobs = plan_jobs(curriculum, args)
    if args.rebuild_word:
        return cmd_rebuild(curriculum, jobs)
    system_prompt = build_system_prompt(CONTENT, curriculum)
    if args.dry_run:
        return cmd_dry_run(jobs, system_prompt, model, args.force, auto_fix)

    todo = [j for j in jobs if args.force or not j.out_path.exists()]
    if not todo:
        print("Everything in this selection is already written. Use --force to rewrite it.")
        return

    import anthropic

    client = make_client()
    checker = StyleChecker.from_rules_file(CONTENT / "style_rules.md")
    system_blocks = [{"type": "text", "text": system_prompt, "cache_control": {"type": "ephemeral"}}]
    if any(j.kind == VIDEO for j in todo):
        system_blocks.append({"type": "text", "text": video_instructions(), "cache_control": {"type": "ephemeral"}})
    totals, results = Totals(), []
    print(f"Writing {len(todo)} documents with {model}.")

    try:
        for index, job in enumerate(todo, start=1):
            print(f"\n[{index}/{len(todo)}] {job.module['title']} ({job.kind})")
            if job.kind == VIDEO:
                result = run_video_job(client, curriculum, system_blocks, job, totals, model, auto_fix)
            else:
                result = run_job(client, curriculum, system_blocks, checker, job, totals, model, auto_fix)
            if result:
                results.append(result)
    except KeyboardInterrupt:
        print("\nStopped. Finished documents are saved. Rerun the same command to continue.")
    except anthropic.AuthenticationError:
        print("\nThe API key was rejected. Check ANTHROPIC_API_KEY in your .env file.")
    except anthropic.NotFoundError:
        print(f"\nModel '{model}' was not found. Check the model name in curriculum.yaml.")
    except anthropic.BadRequestError as err:
        message = str(err)
        if "credit" in message.lower():
            print("\nYour credit balance is too low. Check Settings > Billing in the Claude Console.")
        else:
            print(f"\nThe API rejected the request: {message}")
    except anthropic.APIConnectionError:
        print("\nCould not reach the Claude API. Check your internet connection and rerun.")
    except anthropic.APIStatusError as err:
        print(f"\nThe API returned an error ({err.status_code}). Wait a minute and rerun the same command.")

    if results:
        report = write_report(results, totals, model)
        print(f"\nUsage: {totals.line()}")
        print(f"Report: {report.relative_to(ROOT)}")
        if any(r.job.kind != VIDEO for r in results):
            print(f"Word files: {(OUTPUT / 'word').relative_to(ROOT)}/")
        if any(r.job.kind == VIDEO for r in results):
            print(f"Video scripts: {(OUTPUT / 'video' / 'scripts').relative_to(ROOT)}/")
            print("Next: python3 video/preview.py --module <id>   builds frames and silent previews")


if __name__ == "__main__":
    main()
