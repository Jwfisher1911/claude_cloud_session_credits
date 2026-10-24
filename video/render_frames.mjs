// Render 1920x1080 frames for a VERC lesson video script.
//
// One PNG per build step: a scene with three list items gives b0 (heading only)
// through b3 (all items). assemble.py crossfades between them on the [+] cues.
//
// Usage:
//   node render_frames.mjs <script.yaml> --out <dir> [--assets dir1,dir2] [--worksheets file.json]
//                          [--chapters 1,2] [--only 2:card,3:ray] [--final]
//   --final renders only the last build of each scene (for storyboards).
//   Assets (logo, photos, page images) are looked up in each --assets folder in order.

import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';
import yaml from 'js-yaml';

let chromium;
try { ({ chromium } = await import('playwright')); } catch { ({ chromium } = await import('playwright-core')); }

const here = path.dirname(fileURLToPath(import.meta.url));
const args = process.argv.slice(2);
const opt = (name, dflt) => { const i = args.indexOf(name); return i >= 0 ? args[i + 1] : dflt; };
const scriptPath = args[0];
const assetDirs = opt('--assets', path.join(here, 'assets')).split(',').map(d => path.resolve(d));
const out = path.resolve(opt('--out', path.join(here, 'build', 'frames')));
const worksheets = opt('--worksheets', '') ? JSON.parse(fs.readFileSync(opt('--worksheets'), 'utf8')) : {};
const chapters = opt('--chapters', '') ? opt('--chapters').split(',').map(Number) : null;
const only = opt('--only', '') ? opt('--only').split(',') : null;
const finalOnly = args.includes('--final');

const script = yaml.load(fs.readFileSync(scriptPath, 'utf8'));
const chTitles = script.chapters.map(c => c.title);

// Find every file a scene names in the asset folders.
const wanted = new Set(['verc-logo.png']);
for (const ch of script.chapters) for (const sc of ch.scenes) { if (sc.photo) wanted.add(sc.photo); if (sc.page) wanted.add(sc.page); }
const files = {}, missing = [];
for (const name of wanted) {
  const hit = assetDirs.map(d => path.join(d, name)).find(f => fs.existsSync(f));
  if (hit) files[name] = pathToFileURL(hit).href; else missing.push(name);
}
if (missing.length) console.log(`Not found in ${assetDirs.join(', ')}: ${missing.join(', ')}`);

// Use the browser Playwright installed, or a fixed path when one is set.
const launch = { args: ['--allow-file-access-from-files'] };
const fixed = process.env.CHROMIUM_PATH || (fs.existsSync('/opt/pw-browsers/chromium') ? '/opt/pw-browsers/chromium' : null);
if (fixed) launch.executablePath = fixed;
let browser;
try { browser = await chromium.launch(launch); }
catch (e) {
  console.error('Could not start the browser. From the video folder, run:\n    npx playwright install chromium\n\n' + e.message);
  process.exit(1);
}
const page = await browser.newPage({ viewport: { width: 1920, height: 1080 }, deviceScaleFactor: 1 });
await page.goto(pathToFileURL(path.join(here, 'templates', 'scene.html')).href);
await page.evaluate(() => document.fonts.ready);

const manifest = [];
for (const ch of script.chapters) {
  if (chapters && !chapters.includes(ch.n)) continue;
  const dir = path.join(out, `ch${ch.n}`);
  fs.mkdirSync(dir, { recursive: true });
  for (const [i, sc] of ch.scenes.entries()) {
    if (only && !only.includes(`${ch.n}:${sc.id}`)) continue;
    const meta = { module: script.module, track: script.track || 'core', title: script.title, short: script.short,
      ch: ch.n, chTitle: ch.title, chapters: script.chapters.length, chTitles, files, worksheets };
    const levels = await page.evaluate(([s, m]) => window.renderScene(s, m), [sc, meta]);
    await page.evaluate(() => Promise.all([...document.images].map(im => im.complete ? 0 : new Promise(r => { im.onload = im.onerror = r; }))));
    await page.evaluate(() => document.fonts.ready);
    const shots = [];
    for (let lvl = finalOnly ? levels : 0; lvl <= levels; lvl++) {
      await page.evaluate(l => window.setLevel(l), lvl);
      const f = path.join(dir, `${String(i + 1).padStart(2, '0')}-${sc.id}-b${lvl}.png`);
      await page.screenshot({ path: f, type: 'png' });
      shots.push(path.relative(out, f));
    }
    // Flag text that runs off the frame or into the caption area.
    const overflow = await page.evaluate(() => {
      const bad = [];
      document.querySelectorAll('#stage .content *, #stage .stmt *, #stage .fn *, #stage .title-wrap *, #stage .end > *').forEach(el => {
        const r = el.getBoundingClientRect();
        if (r.width && r.height && (r.right > 1830 || r.bottom > 905)) bad.push(`${el.className || el.tagName} ends at ${Math.round(r.right)}x${Math.round(r.bottom)}`);
      });
      return [...new Set(bad)].slice(0, 4);
    });
    manifest.push({ chapter: ch.n, scene: sc.id, layout: sc.layout, levels, files: shots, overflow });
    console.log(`ch${ch.n} ${sc.id.padEnd(18)} ${sc.layout.padEnd(10)} builds=${levels}${overflow.length ? '  CHECK: ' + overflow.join('; ') : ''}`);
  }
}
// Keep entries from earlier runs for chapters not rendered this time.
const mf = path.join(out, 'manifest.json');
let old = [];
try { old = JSON.parse(fs.readFileSync(mf, 'utf8')); } catch {}
const done = new Set(manifest.map(m => `${m.chapter}:${m.scene}`));
fs.writeFileSync(mf, JSON.stringify([...old.filter(m => !done.has(`${m.chapter}:${m.scene}`)), ...manifest], null, 2));
await browser.close();
