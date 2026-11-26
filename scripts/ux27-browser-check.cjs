// UX-27 browser check: the run tree. Arena menu -> Timeline shows the run's
// shape (agent cycles on the trunk, one branch per route episode, failed
// calls clustered, findings as fruit) on the whole page; what you open slides
// in from the right. The Live view keeps the step log. Against a mock stack
// with a research arena: two agent cycles, five hypotheses (two findings, two
// refuted, one open), sporadic H-MAINT housekeeping at the start and the end.
// NV_UX27_CONFIG: {"arena"}.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const {chromium} = require(process.env.NV_PLAYWRIGHT_MODULE || 'playwright');
const config = JSON.parse(fs.readFileSync(process.env.NV_UX27_CONFIG, 'utf8'));
const WEB = process.env.NV_WEB || 'http://127.0.0.1:15020';
const SHOTS = process.env.NV_UX27_SHOTS || '';

(async () => {
  const browser = await chromium.launch({headless: true,
    executablePath: process.env.NV_CHROMIUM_PATH || undefined, args: ['--no-sandbox']});
  const page = await (await browser.newContext({viewport: {width: 1600, height: 1000}})).newPage();
  const errors = []; page.on('pageerror', error => errors.push(String(error)));
  const checks = [];
  const shot = async name => SHOTS && page.screenshot({path: `${SHOTS}/${name}.png`, fullPage: true});
  const overflow = () => page.evaluate(() => document.documentElement.scrollWidth > window.innerWidth + 1);
  const arena = `${WEB}/console/arena/${config.arena}`;
  const drawer = page.getByRole('dialog');
  try {
    await page.goto(`${arena}?tab=live`);
    await page.getByLabel('Username').fill(process.env.NV_USER || 'admin');
    await page.getByLabel('Password').fill(process.env.NV_PASSWORD || 'nidavellir');
    await page.getByRole('button', {name: 'Sign in'}).click();
    await page.locator('.live-row[role="option"]').first().waitFor();
    assert.equal(await page.locator('.rt-svg').count(), 0);
    checks.push('the Live view is the step log only');

    await page.locator('#rail-arena .rail-link', {hasText: 'Timeline'}).click();
    await page.waitForURL(/tab=timeline/);
    await page.locator('.rt-svg').waitFor();
    assert.match(await page.locator('.rt-head p').first().innerText(), /2 cycles and 6 routes/);
    const marks = await page.locator('.rt-svg *').count();
    assert.ok(marks < 200, `${marks} SVG nodes for the whole run`);
    assert.equal(await page.locator('.rt-ring').count(), 2, 'two agent cycles');
    const names = await page.locator('.rt-branch [role="button"]').evaluateAll(els => els.map(e => e.getAttribute('aria-label').split(':')[0]));
    for (const id of ['H-F1', 'H-F2', 'H-F3', 'H-F4', 'H-F5']) assert.ok(names.includes(id), `branch ${id}`);
    assert.ok(!names.includes('H-MAINT'), 'sporadic housekeeping stays on the trunk');
    assert.equal(await page.locator('.rt-fruit').count(), 2);
    assert.equal(await page.locator('.rt-wither').count(), 2);
    assert.ok(await page.locator('.rt-knot').count() > 0, 'failed calls clustered');
    for (const theme of ['night', 'day']) {
      await page.evaluate(t => localStorage.setItem('nidavellir-theme', t), theme);
      await page.reload();
      await page.locator('.rt-svg').waitFor();
      assert.equal(await overflow(), false, `sideways scroll (${theme})`);
      await shot(`run-tree-${theme}`);
    }
    checks.push(`the run's shape in ${marks} SVG nodes: 2 cycles, 5 hypothesis branches, 2 fruits, 2 withered, failed-call clusters; housekeeping on the trunk`);

    // Hover previews; a click opens the drawer over the page.
    const label = page.locator('.rt-label', {hasText: 'H-F1'});
    await label.hover();
    await page.locator('.rt-card').waitFor();
    assert.match(await page.locator('.rt-card').innerText(), /H-F1/);
    await label.click();
    await drawer.waitFor();
    assert.match(await drawer.locator('h2').innerText(), /H-F1/);
    assert.match(await drawer.innerText(), /Finding/);
    await drawer.getByRole('tab', {name: /^Steps/}).click();
    await drawer.locator('.rt-steps li').first().waitFor();
    assert.ok(await drawer.locator('.rt-steps li').count() > 10);
    await drawer.locator('.rt-steps li button').nth(2).click();
    await drawer.getByText('Input', {exact: true}).waitFor();
    await drawer.getByRole('tab', {name: /^Errors/}).click();
    assert.ok(await drawer.locator('.rt-errors li').count() >= 1);
    await page.keyboard.press('Escape');
    assert.equal(await drawer.count(), 0);
    checks.push('hover previews a route; click opens the drawer: summary, steps with input, errors; Escape closes');

    // A cycle opens its own drawer, which links to the routes it worked.
    await page.locator('.rt-ring').first().click();
    await drawer.waitFor();
    assert.match(await drawer.locator('h2').innerText(), /Cycle 1/);
    await drawer.getByRole('button', {name: 'H-F2'}).click();
    await page.waitForFunction(() => /H-F2/.test(document.querySelector('[role="dialog"] h2')?.textContent || ''));
    await page.locator('.rt-backdrop').click({position: {x: 20, y: 500}});
    assert.equal(await drawer.count(), 0);
    checks.push('a cycle ring opens the cycle, which links to the routes it worked; the backdrop closes the drawer');

    // Search lights the routes that match and steps through them.
    await page.getByLabel('Search the run').fill('secret.txt');
    await page.waitForFunction(() => /steps in \d+ routes/.test(document.querySelector('.rt-search')?.textContent || ''));
    assert.ok(await page.locator('.rt-branch.hit').count() >= 1);
    assert.ok(await page.locator('.rt-branch.dim').count() >= 1);
    await page.locator('.rt-search').getByRole('button', {name: 'Next'}).click();
    await drawer.waitFor();
    await page.keyboard.press('Escape');
    await page.getByLabel('Search the run').fill('');
    await page.waitForFunction(() => !document.querySelector('.rt-branch.hit'));
    checks.push('search lights the matching routes, dims the rest and opens them one by one');

    await page.getByRole('button', {name: 'Only branches with errors'}).click();
    assert.equal(await page.getByRole('button', {name: 'Only branches with errors'}).getAttribute('aria-pressed'), 'true');
    await page.getByRole('button', {name: 'Only branches with errors'}).click();
    const fitH = await page.locator('.rt-svg').evaluate(e => e.getBoundingClientRect().height);
    await page.getByRole('button', {name: 'Roomier'}).click();
    const roomyH = await page.locator('.rt-svg').evaluate(e => e.getBoundingClientRect().height);
    assert.ok(roomyH > fitH * 1.3, `roomier ${roomyH} vs ${fitH}`);
    await page.getByRole('button', {name: 'Fit to page'}).click();
    await page.getByRole('button', {name: 'Replay the run'}).click();
    await page.locator('.rt-clock').waitFor();
    await page.getByRole('button', {name: 'Stop replay'}).click();
    checks.push('error filter, Roomier / Fit to page, and replay with its clock');

    await page.setViewportSize({width: 390, height: 844});
    await page.reload();
    await page.locator('.rt-svg').waitFor();
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
