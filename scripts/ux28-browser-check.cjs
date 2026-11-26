// UX-28 browser check: the timeline as a serpent. Arena menu -> Timeline draws
// the run against its time budget: the serpent grows clockwise from its tail,
// findings and failed calls sprout outside, verdicts inside; the side panel is
// the run in numbers; a mark opens what it groups and a finding opens its
// report. The Live view keeps the step log. Against a mock stack with a
// research arena six hours into a 24-hour lease: twenty hypotheses (eight
// with findings, one of them a duplicate), failed calls and one refusal.
// NV_UX28_CONFIG: {"arena"}.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const {chromium} = require(process.env.NV_PLAYWRIGHT_MODULE || 'playwright');
const config = JSON.parse(fs.readFileSync(process.env.NV_UX28_CONFIG, 'utf8'));
const WEB = process.env.NV_WEB || 'http://127.0.0.1:15020';
const SHOTS = process.env.NV_UX28_SHOTS || '';

(async () => {
  const browser = await chromium.launch({headless: true,
    executablePath: process.env.NV_CHROMIUM_PATH || undefined, args: ['--no-sandbox']});
  const page = await (await browser.newContext({viewport: {width: 1600, height: 1000}})).newPage();
  const errors = []; page.on('pageerror', error => errors.push(String(error)));
  const checks = [];
  const shot = async name => SHOTS && page.screenshot({path: `${SHOTS}/${name}.png`, fullPage: true});
  const overflow = () => page.evaluate(() => document.documentElement.scrollWidth > window.innerWidth + 1);
  const arena = `${WEB}/console/arena/${config.arena}`;
  const side = page.locator('.tl-side');
  try {
    await page.goto(`${arena}?tab=live`);
    await page.getByLabel('Username').fill(process.env.NV_USER || 'admin');
    await page.getByLabel('Password').fill(process.env.NV_PASSWORD || 'nidavellir');
    await page.getByRole('button', {name: 'Sign in'}).click();
    await page.locator('.live-row[role="option"]').first().waitFor();
    assert.equal(await page.locator('.tl-svg').count(), 0);
    checks.push('the Live view is the step log only');

    await page.locator('#rail-arena .rail-link', {hasText: 'Timeline'}).click();
    await page.waitForURL(/tab=timeline/);
    await page.locator('.tl-svg').waitFor();
    await page.waitForFunction(() => !document.querySelector('.tl-mark.fut'));  // replay on open ends
    assert.match(await page.locator('.tl-centre .of').textContent(), /of 24 h/);
    assert.match(await page.locator('.tl-centre .pct').textContent(), /^2[4-7]\.\d% · 1[78] h/);
    assert.equal(await page.locator('.tl-head').count(), 1);
    const nodes = await page.locator('.tl-svg *').count();
    assert.ok(nodes < 900, `${nodes} SVG nodes for the whole run`);
    const marks = await page.locator('.tl-mark').count();
    assert.ok(marks >= 10 && marks < 80, `${marks} marks`);
    assert.ok(await page.locator('.tl-gem.echo').count() >= 1, 'the duplicate is drawn hollow');
    checks.push('the serpent covers a quarter of the 24-hour circle, with grouped marks and the duplicate hollow');

    await shot('timeline');
    await side.getByText('The run in numbers').waitFor();
    assert.match(await side.getByRole('meter', {name: 'Time budget'}).getAttribute('aria-valuenow'), /^2[4-7]$/);
    for (const label of ['Hypothesis verdicts', 'Findings by severity', 'Where the steps went'])
      await side.getByText(label).waitFor();
    assert.equal(await side.locator('.tl-list li').count(), 8);
    checks.push('the side panel is the run in numbers: budget meters, verdict, severity and tool shares, findings');

    const grouped = page.locator('.tl-mark.out').filter({has: page.locator('.tl-gem text')}).first();
    await grouped.hover();
    await page.locator('.tl-card').waitFor();
    assert.match(await page.locator('.tl-card').textContent(), /findings/);
    await grouped.click();
    await side.getByRole('button', {name: '← Back to the run'}).waitFor();
    assert.ok(await side.locator('.tl-list button').count() >= 2);
    await side.locator('.tl-list button').first().click();
    await side.locator('.fr').waitFor();
    await side.getByRole('button', {name: 'Copy report'}).waitFor();
    assert.ok(await page.locator('.tl-main.reading').count() === 1, 'the report widens the panel');
    await shot('report');
    await page.keyboard.press('Escape');
    await side.getByRole('button', {name: '← Back to the run'}).waitFor();
    await page.keyboard.press('Escape');
    await side.getByText('The run in numbers').waitFor();
    checks.push('a grouped mark opens its findings; a finding opens its report; Escape walks back');

    await page.getByRole('button', {name: 'Preview the end'}).click();
    await page.waitForFunction(() => /bites its tail/.test(document.querySelector('.tl-centre .pct')?.textContent || ''));
    assert.equal(await page.locator('.tl-head.bitten').count(), 1);
    await shot('bitten');
    await page.getByRole('button', {name: 'Preview the end'}).click();
    await page.getByRole('button', {name: 'Replay'}).click();
    await page.waitForFunction(() => document.querySelector('.tl-mark.fut'));
    checks.push('Preview the end closes the circle and the serpent bites; Replay regrows it');

    await page.setViewportSize({width: 390, height: 844});
    await page.reload();
    await page.locator('.tl-svg').waitFor();
    assert.equal(await overflow(), false, 'sideways scroll at 390 px');
    checks.push('no sideways scroll at 390 px');

    assert.deepEqual(errors, []);
    console.log(JSON.stringify({ok: true, checks}, null, 2));
  } catch (error) {
    await shot('failure');
    console.log(JSON.stringify({ok: false, checks, errors, error: String(error.stack || error)}, null, 2));
    process.exitCode = 1;
  } finally {
    await browser.close();
  }
})();
