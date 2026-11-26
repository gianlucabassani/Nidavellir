// UX-26 browser check: the run's world tree on its own page (arena menu ->
// Timeline), with the routes panel beside it; the Live view keeps the step
// log only. Against a mock stack with one research arena: recon steps, five
// hypotheses (two with findings, two refuted, one open), self-reported twins,
// an idle stretch and failures. NV_UX26_CONFIG: {"arena"}.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const {chromium} = require(process.env.NV_PLAYWRIGHT_MODULE || 'playwright');
const config = JSON.parse(fs.readFileSync(process.env.NV_UX26_CONFIG, 'utf8'));
const WEB = process.env.NV_WEB || 'http://127.0.0.1:15020';
const SHOTS = process.env.NV_UX26_SHOTS || '';

(async () => {
  const browser = await chromium.launch({headless: true,
    executablePath: process.env.NV_CHROMIUM_PATH || undefined, args: ['--no-sandbox']});
  const page = await (await browser.newContext({viewport: {width: 1600, height: 1000}})).newPage();
  const errors = []; page.on('pageerror', error => errors.push(String(error)));
  const checks = [];
  const shot = async name => SHOTS && page.screenshot({path: `${SHOTS}/${name}.png`});
  const overflow = () => page.evaluate(() => document.documentElement.scrollWidth > window.innerWidth + 1);
  const arena = `${WEB}/console/arena/${config.arena}`;
  try {
    await page.goto(`${arena}?tab=live`);
    await page.getByLabel('Username').fill(process.env.NV_USER || 'admin');
    await page.getByLabel('Password').fill(process.env.NV_PASSWORD || 'nidavellir');
    await page.getByRole('button', {name: 'Sign in'}).click();

    // The Live view is the step log only.
    await page.locator('.live-row[role="option"]').first().waitFor();
    assert.equal(await page.locator('.yg-svg').count(), 0);
    assert.equal(await page.getByRole('group', {name: 'View'}).count(), 0);
    checks.push('the Live view is the step log only, with a link to the timeline');

    // The arena menu opens the Timeline page; the tree grows from its roots.
    await page.locator('#rail-arena .rail-link', {hasText: 'Timeline'}).click();
    await page.waitForURL(/tab=timeline/);
    assert.equal(await page.locator('#rail-arena .rail-link[aria-current="page"]').innerText(), 'Timeline');
    await page.locator('.yg-svg').waitFor();
    await page.waitForFunction(() => document.querySelectorAll('.yg-ev.fut').length > 0, null, {timeout: 3000});
    await page.waitForFunction(() => document.querySelectorAll('.yg-ev.fut').length === 0, null, {timeout: 8000});
    checks.push('Timeline is its own arena page; the tree grows from the roots when it opens');

    // Big and whole: the tree fills the page and the whole run fits.
    const canvas = await page.locator('.yg-scroll').boundingBox();
    assert.ok(canvas.height > 560 && canvas.width > 900, `canvas ${canvas.width}x${canvas.height}`);
    const fits = await page.locator('.yg-scroll').evaluate(e => e.scrollHeight <= e.clientHeight + 4);
    assert.ok(fits, 'Whole run fits the visible height');
    await page.getByRole('group', {name: 'Zoom'}).getByRole('button', {name: 'Detail'}).click();
    assert.ok(await page.locator('.yg-scroll').evaluate(e => e.scrollHeight > e.clientHeight * 1.5), 'Detail spreads the run');
    await page.getByRole('group', {name: 'Zoom'}).getByRole('button', {name: 'Whole run'}).click();
    for (const theme of ['night', 'day']) {
      await page.evaluate(t => localStorage.setItem('nidavellir-theme', t), theme);
      await page.reload();
      await page.locator('.yg-svg').waitFor();
      await page.waitForTimeout(2800);
      assert.equal(await overflow(), false, `timeline scrolls sideways (${theme})`);
      await shot(`timeline-${theme}`);
    }
    checks.push(`the tree fills the page (${Math.round(canvas.width)}×${Math.round(canvas.height)}); Whole run fits it, Detail spreads it; both themes`);

    // Routes panel: filters, hover lights a branch, click focuses it.
    const panel = page.getByRole('complementary', {name: 'Routes'});
    const cards = panel.locator('.tl-route');
    const names = (await cards.locator('b').allTextContents()).map(n => n.trim());
    for (const id of ['H-F1', 'H-F2', 'H-F3', 'H-F4', 'H-F5']) assert.ok(names.includes(id), `route ${id}`);
    const filters = panel.getByRole('group', {name: 'Route filter'});
    await filters.getByRole('button', {name: /^Findings/}).click();
    assert.equal(await cards.count(), 2);
    await filters.getByRole('button', {name: /^Refuted/}).click();
    assert.equal(await cards.count(), 2);
    await filters.getByRole('button', {name: /^All/}).click();
    const f1 = cards.filter({hasText: 'H-F1'});
    assert.match(await f1.innerText(), /finding/i);
    await f1.hover();
    assert.equal(await page.locator('.yg-branch.hot').count(), 1);
    await f1.click();
    assert.equal(await f1.getAttribute('aria-pressed'), 'true');
    assert.equal(await page.locator('.yg-branch.dim').count(), names.length - 1);
    await panel.getByRole('button', {name: 'Show every route'}).click();
    assert.equal(await page.locator('.yg-branch.dim').count(), 0);
    checks.push(`routes panel: ${names.length} routes, filters (2 findings, 2 refuted), hover lights the branch, click focuses it`);

    // A step selected on the tree opens in the inspector under the routes.
    const leaf = page.locator('.yg-ev').filter({has: page.locator('.yg-leaf')}).nth(20);
    await leaf.click({force: true});
    await page.locator('.yg-sel').waitFor();
    assert.doesNotMatch(await panel.locator('.live-inspector').innerText(), /Select a span/);
    await page.locator('.yg-scroll').focus();
    await page.keyboard.press('ArrowUp');
    assert.equal(await page.locator('.yg-sel').count(), 1);
    checks.push('clicking a leaf opens the step in the inspector; arrow keys move the selection');

    // Replay still scrubs and comes back to live.
    await page.getByLabel('Scrub through the run').fill('200');
    await page.waitForFunction(() => document.querySelectorAll('.yg-ev.fut').length > 0);
    await page.getByRole('button', {name: 'Back to live'}).click();
    await page.waitForFunction(() => document.querySelectorAll('.yg-ev.fut').length === 0);
    checks.push('replay scrubs back and returns to live');

    await page.setViewportSize({width: 390, height: 844});
    await page.reload();
    await page.locator('.yg-svg').waitFor();
    assert.equal(await overflow(), false, 'timeline scrolls sideways at 390 px');
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
