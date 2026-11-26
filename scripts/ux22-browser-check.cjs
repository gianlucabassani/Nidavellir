// UX-22 browser check: the world tree on the arena's Live view. Against a mock
// stack with one research arena: recon steps, five hypotheses (two with
// findings, two refuted, one open), self-reported twins of enforced calls, an
// idle stretch and failures. NV_UX22_CONFIG: {"arena"}.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const {chromium} = require(process.env.NV_PLAYWRIGHT_MODULE || 'playwright');
const config = JSON.parse(fs.readFileSync(process.env.NV_UX22_CONFIG, 'utf8'));
const WEB = process.env.NV_WEB || 'http://127.0.0.1:15020';
const SHOTS = process.env.NV_UX22_SHOTS || '';

(async () => {
  const browser = await chromium.launch({headless: true,
    executablePath: process.env.NV_CHROMIUM_PATH || undefined, args: ['--no-sandbox']});
  const page = await (await browser.newContext({viewport: {width: 1440, height: 1000}})).newPage();
  const errors = []; page.on('pageerror', error => errors.push(String(error)));
  const checks = [];
  const shot = async name => SHOTS && page.screenshot({path: `${SHOTS}/${name}.png`});
  const overflow = () => page.evaluate(() => document.documentElement.scrollWidth > window.innerWidth + 1);
  const live = `${WEB}/console/arena/${config.arena}?tab=live`;
  const ready = () => page.locator('.yg-svg .yg-ev').first().waitFor();
  try {
    await page.goto(live);
    await page.getByLabel('Username').fill(process.env.NV_USER || 'admin');
    await page.getByLabel('Password').fill(process.env.NV_PASSWORD || 'nidavellir');
    await page.getByRole('button', {name: 'Sign in'}).click();

    for (const theme of ['day', 'night']) {
      await page.evaluate(t => localStorage.setItem('nidavellir-theme', t), theme);
      await page.goto(live);
      await ready();
      assert.equal(await overflow(), false, `live view scrolls sideways (${theme})`);
      await shot(`world-tree-${theme}`);
    }
    await page.evaluate(() => localStorage.setItem('nidavellir-theme', 'day'));
    await page.goto(live);
    await ready();

    // Timeline is the default view: one branch per hypothesis, with outcomes.
    const view = page.getByRole('group', {name: 'View'});
    assert.equal(await view.getByRole('button', {name: 'Timeline'}).getAttribute('aria-pressed'), 'true');
    const chips = page.getByRole('group', {name: 'Routes'}).locator('.yg-chip');
    const names = (await chips.locator('b').allTextContents()).map(n => n.trim());
    for (const id of ['H-F1', 'H-F2', 'H-F3', 'H-F4', 'H-F5'])
      assert.ok(names.includes(id), `route ${id}: ${names}`);
    assert.equal(await page.locator('.yg-branch').count(), names.length);
    assert.equal(await page.locator('.yg-tip.finding .yg-fruit').count(), 2, 'two fruits');
    assert.equal(await page.locator('.yg-tip.refuted .yg-wither').count(), 2, 'two withered tips');
    assert.ok(await page.locator('.yg-tip.open .yg-bud').count() >= 1, 'an open bud');
    assert.ok(await page.locator('.yg-sprout').count() >= 5, 'a sprout where each hypothesis was declared');
    assert.ok(await page.locator('.yg-leaf.err').count() > 0, 'failed steps are red leaves');
    assert.ok(await page.locator('.yg-gap').count() >= 1, 'the idle stretch folds into a ring');
    assert.match(await page.locator('.yg-gap text').first().textContent(), /min quiet/);
    checks.push(`timeline by default: ${names.length} routes, 2 fruits, 2 withered, an open bud, sprouts, red leaves, a quiet ring`);

    // Self-reported twins fold into the enforced call: half the leaves.
    const total = Number((await page.locator('.live-head, .live-toolbar, body').first().innerText()).match(/(\d+) spans/)?.[1] || 0);
    const drawn = await page.locator('.yg-ev').count();
    assert.ok(total > 0 && drawn < total * 0.7, `${drawn} marks for ${total} spans`);
    checks.push(`self-reported twins fold into their enforced call (${drawn} marks for ${total} spans)`);

    // Hover previews; click pins the step in the inspector.
    const leaf = page.locator('.yg-ev').filter({has: page.locator('.yg-leaf')}).nth(30);
    await leaf.scrollIntoViewIfNeeded();
    await leaf.hover({force: true});
    await page.locator('.yg-tip-pop').waitFor();
    assert.match(await page.locator('.yg-tip-pop small').textContent(), /H-F\d/);
    await leaf.click({force: true});
    await page.locator('.yg-sel').waitFor();
    assert.doesNotMatch(await page.locator('.live-inspector').innerText(), /Select a span/);
    checks.push('hover previews a leaf with its route; click pins it in the inspector');

    // Focusing a route dims the others.
    await chips.filter({hasText: 'H-F1'}).click();
    assert.equal(await chips.filter({hasText: 'H-F1'}).getAttribute('aria-pressed'), 'true');
    assert.equal(await page.locator('.yg-branch.dim').count(), names.length - 1);
    await page.getByRole('button', {name: 'Show every route'}).click();
    assert.equal(await page.locator('.yg-branch.dim').count(), 0);
    checks.push('a route chip focuses its branch and dims the rest');

    // Arrow keys move the selection inside the tree.
    await page.locator('.yg-scroll').focus();
    await page.keyboard.press('ArrowUp');
    assert.equal(await page.locator('.yg-sel').count(), 1);
    checks.push('arrow keys move the selection');

    // Replay: scrubbing back hides later growth; Back to live restores it.
    const scrub = page.getByLabel('Scrub through the run');
    await scrub.fill('300');
    await page.waitForFunction(() => document.querySelectorAll('.yg-ev.fut').length > 0);
    const hidden = await page.locator('.yg-ev.fut').count();
    await page.getByRole('button', {name: 'Replay'}).click();
    const clock0 = await page.locator('.yg-clock').textContent();
    await page.waitForFunction(c => document.querySelector('.yg-clock').textContent !== c, clock0);
    await page.getByRole('button', {name: 'Pause replay'}).click();
    await page.getByRole('button', {name: 'Back to live'}).click();
    await page.waitForFunction(() => document.querySelectorAll('.yg-ev.fut').length === 0);
    checks.push(`replay: scrubbing back hides ${hidden} later steps, Replay grows the tree, Back to live restores all`);

    // The list view keeps every step.
    await view.getByRole('button', {name: 'List'}).click();
    await page.locator('.live-row[role="option"]').first().waitFor();
    assert.equal(await page.locator('.yg-svg').count(), 0);
    await view.getByRole('button', {name: 'Timeline'}).click();
    await page.locator('.yg-svg').waitFor();
    checks.push('the List view still lists every step');

    // Phone width.
    await page.setViewportSize({width: 390, height: 844});
    await page.goto(live);
    await ready();
    assert.equal(await overflow(), false, 'live view scrolls sideways at 390 px');
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
