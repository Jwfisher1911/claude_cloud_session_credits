# VERC Course Generator

Drafts VERC lesson guides and printable workbooks with the Claude API and saves them as Word documents. It runs on your Claude Console API credits.

What it writes right now:
- **VERC Core Modules** (7 modules): Operational Battle Rhythm, Your One-Page Business Brief, Building Your AI Staff, Google Business Profile and Search Console, Facebook Page Setup and Verification, Instagram Setup for Business, Launching Your First Social Media Ads.
- **VetCert Readiness** (4 modules): What It Is and Who Qualifies, Getting Ready, Ownership and Control, Submitting and Staying Certified.

Each module produces two Word files: a **Lesson Guide** and a **Workbook**. Every draft gets checked against the VERC writing rules (no em dashes, no banned words, and so on) and gets one automatic revision if it breaks them.

It also writes a **lesson video script** for each module, one short chapter per lesson, and builds silent previews with captions. See [Lesson videos](#lesson-videos). A voice track gets added later.

---

## Setup on your Mac (one time, about 10 minutes)

### 1. Download the code
Open **Terminal** (press Command + Space, type Terminal, press Return) and run:

```
cd ~/Documents
git clone https://github.com/Jwfisher1911/claude_cloud_session_credits.git
cd claude_cloud_session_credits
```

If your Mac asks to install "command line developer tools," click Install, wait for it to finish, and run the commands again.

### 2. Install the Python packages

```
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

### 3. Add your API key
1. In the Claude Console, open **API Keys** and create a key. Make sure you are in the organization holding your credit grant.
2. In Terminal, run:
   ```
   cp .env.example .env
   open -e .env
   ```
3. Paste your key after `ANTHROPIC_API_KEY=` and save the file.

The `.env` file stays on your Mac. It never goes to GitHub.

### 4. Test without spending credits

```
python3 generate.py --preview
open output/word/_layout-preview-workbook.docx
```

This builds two short sample files so you see the Word layout. Then check the plan:

```
python3 generate.py --dry-run
```

---

## Writing the drafts

Start with one module and review it before running the rest:

```
python3 generate.py --module battle-rhythm
open output/word/core
```

Then run a whole track, or everything:

```
python3 generate.py --track core
python3 generate.py --track vetcert
python3 generate.py
```

Every time you open a new Terminal window, run these two lines first:

```
cd ~/Documents/claude_cloud_session_credits
source .venv/bin/activate
```

### All commands

| Command | What it does | Uses credits? |
|---|---|---|
| `python3 generate.py --list` | Lists every module and its id | No |
| `python3 generate.py --dry-run` | Shows what would be written | No |
| `python3 generate.py --preview` | Builds sample Word files to check the layout | No |
| `python3 generate.py --module ai-staff` | Writes one module (lesson + workbook) | Yes |
| `python3 generate.py --module ai-staff --kind workbook` | Writes only the workbook | Yes |
| `python3 generate.py --track core` | Writes every core module | Yes |
| `python3 generate.py --module ai-staff --force` | Rewrites a module already written | Yes |
| `python3 generate.py --rebuild-word` | Rebuilds Word files from the saved drafts after you change colors or edit a draft | No |
| `python3 generate.py --kind video` | Writes a video script for every module with a lesson guide | Yes |
| `python3 generate.py --module ai-staff --kind video` | Writes the video script for one module | Yes |
| `python3 video/preview.py --module ai-staff --frames-only` | Builds the storyboard page for one module (about 20 seconds) | No |
| `python3 video/preview.py --module ai-staff` | Builds the storyboard plus a silent preview MP4 for every chapter | No |

---

## Where things go

| Folder | Contents |
|---|---|
| `output/word/` | Finished Word files, one folder per track |
| `output/markdown/` | The plain-text drafts the Word files are built from |
| `output/reports/` | One report per run: style issues left, VERIFY notes to check, token usage |
| `output/video/scripts/` | Lesson video scripts (YAML), one per module |
| `output/video/storyboards/` | One folder per module: `index.html` storyboard, chapter previews (`ch1.mp4`...), caption files (`ch1.vtt`...) |
| `output/video/assets/` | Photos you add for video scenes |

The `output/` folder stays on your Mac and is not uploaded to GitHub.

## Changing what gets written

| File | Edit it to change |
|---|---|
| `content/curriculum.yaml` | Modules, lesson topics, worksheets, model, colors, lesson length |
| `content/brand.md` | VERC background, audience, teaching approach |
| `content/style_rules.md` | Writing rules and the banned word list (the checker reads this list too) |
| `content/sources/vetcert_facts.md` | Approved VetCert facts. Claude uses only these for program rules. |

After an edit, rewrite the affected module with `--force`.

## Lesson videos

Each module becomes a video in short chapters, one per lesson, 2 to 3 minutes each, at 1920 x 1080 with captions. Every chapter ends by sending the viewer to a worksheet in the workbook. The look matches the VERC launch video.

### One-time setup on your Mac

The previews need two free tools, Node.js and ffmpeg. Install them with Homebrew:

```
brew install node ffmpeg
```

No Homebrew yet? Install it first from [brew.sh](https://brew.sh) (one line to paste into Terminal), then run the line above.

Then, from this folder:

```
source .venv/bin/activate
pip install -r requirements.txt
cd video && npm install && npx playwright install chromium && cd ..
```

### Write the scripts

The video script is written from the lesson guide and workbook, so write those first. Then:

```
python3 generate.py --kind video --dry-run
python3 generate.py --module five-ws --kind video
```

Review the first one before you run the rest with `python3 generate.py --kind video`. Module 1 (Battle Rhythm) uses the script already approved in `video/scripts/core/`, so it costs nothing.

Each script is checked before it is saved: the right number of on-screen items for each scene, text short enough to fit the frame, every task scene pointing at a real worksheet, and the VERC writing rules. A script that fails gets one automatic revision. Anything left shows up in the run report.

Cost with `claude-opus-5-5`: about $0.15 to $0.30 per module, so about $2 to $3 for all ten.

### Watch the previews

```
python3 video/preview.py --module five-ws --frames-only
open output/video/storyboards/02-five-ws/index.html
```

The storyboard page shows every scene's frame beside its narration. Drop `--frames-only` to also build a silent MP4 for each chapter, with captions timed to an estimated reading pace. Each chapter takes a few minutes to encode. Use `--chapters 1` to build only the first.

### Edit a script

Open the YAML file in `output/video/scripts/` in TextEdit and change the words. Two rules:
- A `[+]` in the narration marks the moment the next item appears on screen. Keep one `[+]` per item.
- Keep the indentation as it is.

Then check it and rebuild the preview:

```
python3 video/script_tools.py output/video/scripts/core/02-five-ws-video.yaml
python3 video/preview.py --module five-ws --frames-only
```

### Photos

Scenes with the `photo` layout need the photo in `output/video/assets/`. The preview marks a missing photo with "Photo needed". For DVIDS photos, keep the DoD disclaimer: add `dod: true` to the chapter's last scene.

### Voice

The previews are silent. When the voice is ready (your own recording, or an ElevenLabs voice), the same cues get timed to the voice, and each chapter is rebuilt with narration, captions, and an MP3 version.

## Before you publish
1. Open the newest report in `output/reports/`.
2. Check every yellow **VERIFY** note in the Word files. Claude adds one wherever a fact is not in the approved sources.
3. Recheck VetCert rules at sba.gov/vetcert. The facts file was verified on October 22, 2026.
4. Have an attorney review anything about governing documents, ownership, or control.

## Controlling cost
- **Model:** `claude-opus-5-5` writes the strongest drafts. Change `model` in `content/curriculum.yaml` to `claude-sonnet-5-5` to spend less per document.
- **Revisions:** set `auto_fix: false` to skip the automatic style revision.
- **No repeats:** documents already written are skipped. Stop any time with Control + C and rerun the same command to continue.
- **Prompt caching:** the shared instructions (about 5,000 tokens) are cached after the first request in a run, so later requests read them at a reduced rate. Check `cache read` in the run summary.
- Track your balance in the Claude Console under **Settings > Billing**.

## Run it with Claude Code instead
In Terminal, inside this folder, run `claude` and type: "Set up this project and run the generator for the battle-rhythm module." Claude Code reads this README and runs the steps for you.

## Offline test
`python3 tests/smoke_test.py` runs the whole pipeline, video scripts included, with a fake Claude client. No key needed, no credits spent.

---

VERC is a d/b/a of Casa Concepts LLC. VERC is not affiliated with the Department of Defense, the U.S. Small Business Administration, or the Department of Veterans Affairs. SBA makes every certification decision.
