#!/usr/bin/env node
// Project-owned browser contracts: stable screenshots, computed styles, a11y and layout.
import fs from 'node:fs/promises';
import path from 'node:path';
import process from 'node:process';
import { createRequire } from 'node:module';
import { parseArgs } from 'node:util';

const { values } = parseArgs({ options: {
  project: { type: 'string', default: process.cwd() },
  config: { type: 'string', default: '.ai/quality-browser.json' },
  'base-url': { type: 'string' },
  'update-baselines': { type: 'boolean', default: false },
  'allow-remote-target': { type: 'boolean', default: false },
} });
const root = await fs.realpath(values.project);
async function within(name, writable = false) {
  if (path.isAbsolute(name) || name.split(/[\\/]/).includes('..')) throw new Error('Use project-relative paths');
  if (name.split(/[\\/]/).some(part => ['.git', 'secrets', 'sessions', 'backups'].includes(part) || part.startsWith('.env'))) {
    throw new Error('Protected artifact/config path');
  }
  const target = path.resolve(root, name);
  if (!target.startsWith(root + path.sep)) throw new Error('Path escapes project');
  let current = root;
  for (const part of name.split(path.sep)) {
    current = path.join(current, part);
    try { if ((await fs.lstat(current)).isSymbolicLink()) throw new Error('Symlink artifact/config path'); }
    catch (error) { if (!writable || error.code !== 'ENOENT') throw error; }
  }
  return target;
}
const config = JSON.parse(await fs.readFile(await within(values.config), 'utf8'));
if (config.version !== 1 || !Array.isArray(config.pages) || !config.pages.length || config.pages.length > 12) {
  throw new Error('Configure 1–12 explicit pages');
}
const base = new URL(values['base-url'] || config.baseURL);
if (!['http:', 'https:'].includes(base.protocol) || base.username || base.password) throw new Error('Invalid base URL');
if (!['127.0.0.1', 'localhost', '[::1]'].includes(base.hostname) && !values['allow-remote-target']) {
  throw new Error('Nonlocal browser targets require --allow-remote-target');
}
const require = createRequire(path.join(root, 'package.json'));
const bundledRequire = createRequire(import.meta.url);
function dependency(name) {
  try { return require.resolve(name); }
  catch (error) { if (error.code !== 'MODULE_NOT_FOUND') throw error; return bundledRequire.resolve(name); }
}
const { chromium } = require(dependency('playwright'));
const { PNG } = require(dependency('pngjs'));
const pixelmatchModule = await import(dependency('pixelmatch'));
const pixelmatch = pixelmatchModule.default || pixelmatchModule;
const axePath = dependency('axe-core/axe.min.js');
const baselineRoot = await within(config.baselines || '.ai/visual-baselines', true);
const artifactRoot = await within(config.artifacts || '.ai/quality-artifacts', true);
await fs.mkdir(artifactRoot, { recursive: true });
const runRoot = await fs.mkdtemp(path.join(artifactRoot, 'run-'));
const widths = config.widths || [375, 768, 1024, 1440];
if (!Array.isArray(widths) || !widths.length || widths.length > 8 || widths.some(n => !Number.isInteger(n) || n < 320 || n > 1920)) {
  throw new Error('Configure 1–8 viewports in [320,1920]');
}
for (const value of [config.pixelThreshold ?? 0.1, config.maxChangedPixelRatio ?? 0.001]) {
  if (!Number.isFinite(value) || value < 0 || value > 1) throw new Error('Pixel budgets must be fractions in [0,1]');
}
const failures = [];
const measurements = [];
const browser = await chromium.launch({ headless: true, executablePath: process.env.QUALITY_CHROMIUM_EXECUTABLE || undefined });
try {
  for (const spec of config.pages) {
    if (!/^[a-z0-9_-]{1,64}$/i.test(spec.id) || typeof spec.path !== 'string') throw new Error('Page needs a safe ID and path');
    const url = new URL(spec.path, base);
    if (url.origin !== base.origin) throw new Error('Page escapes configured origin');
    for (const width of widths) {
      const context = await browser.newContext({ viewport: { width, height: config.height || 900 },
        colorScheme: config.colorScheme || 'light', reducedMotion: 'reduce', locale: 'en-US', timezoneId: 'UTC',
        serviceWorkers: 'block' });
      const approved = new Set([base.origin, ...(config.allowedResourceOrigins || [])]);
      await context.route('**/*', route => approved.has(new URL(route.request().url()).origin) ? route.continue() : route.abort());
      const page = await context.newPage();
      const label = `${spec.id}-${width}`;
      try {
        await page.goto(url.href, { waitUntil: 'networkidle', timeout: 30000 });
        await page.evaluate(() => document.fonts.ready);
        if (spec.ready) await page.locator(spec.ready).waitFor();
        if (spec.style) await page.addStyleTag({ content: spec.style });
        const overflow = await page.evaluate(() => document.documentElement.scrollWidth > window.innerWidth + 1);
        if (overflow) failures.push({ page: label, check: 'horizontal-overflow' });
        for (const check of spec.computed || []) {
          const actual = await page.locator(check.selector).evaluate((element, property) =>
            getComputedStyle(element).getPropertyValue(property).trim(), check.property);
          if (actual !== String(check.equals)) failures.push({ page: label, check: 'computed-style', ...check, actual });
        }
        for (const selector of spec.keyboardOrder || []) {
          await page.keyboard.press('Tab');
          if (!await page.locator(selector).evaluate(element => element === document.activeElement)) {
            failures.push({ page: label, check: 'keyboard-order', selector });
          }
        }
        await page.addScriptTag({ path: axePath });
        const accessibility = await page.evaluate(() => window.axe.run(document, {
          runOnly: { type: 'tag', values: ['wcag2a', 'wcag2aa', 'wcag21aa', 'wcag22aa'] },
        }));
        for (const issue of accessibility.violations) failures.push({ page: label, check: 'accessibility',
          rule: issue.id, impact: issue.impact, selectors: issue.nodes.slice(0, 5).map(n => n.target) });
        const png = await page.screenshot({ path: path.join(runRoot, label + '.png'), fullPage: true, animations: 'disabled' });
        const baseline = path.join(baselineRoot, label + '.png');
        try { if ((await fs.lstat(baseline)).isSymbolicLink()) throw new Error('Symlink baseline file'); }
        catch (error) { if (error.code !== 'ENOENT') throw error; }
        if (values['update-baselines']) {
          await fs.mkdir(baselineRoot, { recursive: true });
          // Baseline replacement is a separate, explicit operator action.
          await fs.writeFile(baseline, png);
        } else {
          try {
            const expected = PNG.sync.read(await fs.readFile(baseline));
            const actual = PNG.sync.read(png);
            if (expected.width !== actual.width || expected.height !== actual.height) {
              failures.push({ page: label, check: 'screenshot-dimensions' });
            } else {
              const diff = new PNG({ width: actual.width, height: actual.height });
              const changed = pixelmatch(expected.data, actual.data, diff.data, actual.width, actual.height,
                { threshold: config.pixelThreshold ?? 0.1 });
              const ratio = changed / (actual.width * actual.height);
              measurements.push({ page: label, changedPixelRatio: ratio });
              if (ratio > (config.maxChangedPixelRatio ?? 0.001)) {
                await fs.writeFile(path.join(runRoot, label + '-diff.png'), PNG.sync.write(diff));
                failures.push({ page: label, check: 'visual-regression', changedPixelRatio: ratio });
              }
            }
          } catch (error) {
            if (error.code === 'ENOENT') failures.push({ page: label, check: 'missing-baseline' });
            else throw error;
          }
        }
      } catch (error) { failures.push({ page: label, check: 'browser', message: error.message.slice(0, 500) }); }
      finally { await context.close(); }
    }
  }
} finally { await browser.close(); }
const report = { status: failures.length ? 'failed' : 'passed', failures, measurements,
  baselineUpdate: values['update-baselines'], browserVersion: browser.version(), widths, artifacts: runRoot };
await fs.writeFile(path.join(runRoot, 'report.json'), JSON.stringify(report, null, 2));
console.log(JSON.stringify({ ...report, failures: failures.slice(0, 6), omitted: Math.max(0, failures.length - 6),
  measurements: measurements.slice(0, 6), measurementsOmitted: Math.max(0, measurements.length - 6) }));
process.exitCode = failures.length ? 1 : 0;
