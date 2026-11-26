// UX-19 browser check: the forge line on the arena's Live view. Against a
// mock stack with one arena holding a two-actor run (spans over ~80 minutes,
// failures, findings, an idle stretch). NV_UX19_CONFIG: {"arena"}.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const {chromium} = require(process.env.NV_PLAYWRIGHT_MODULE || 'playwright');
const config = JSON.parse(fs.readFileSync(process.env.NV_UX19_CONFIG, 'utf8'));
const WEB = process.env.NV_WEB || 'http://127.0.0.1:15020';
const SHOTS = process.env.NV_UX19_SHOTS || '';

(async () => {
  const browser = await chromium.launch({headless: true,
    executablePath: process.env.NV_CHROMIUM_PATH || undefined, args: ['--no-sandbox']});
  const page = await (await browser.newContext({viewport: {width: 1440, height: 1000}})).newPage();
  const errors = []; page.on('pageerror', error => errors.push(String(error)));
  const checks = [];
  const shot = async name => SHOTS && page.screenshot({path: `${SHOTS}/${name}.png`});
  const overflow = () => page.evaluate(() => document.documentElement.scrollWidth > window.innerWidth + 1);
  const live = `${WEB}/console/arena/${config.arena}?tab=live`;
  try {
    await page.goto(live);
    await page.getByLabel('Username').fill(process.env.NV_USER || 'admin');
    await page.getByLabel('Password').fill(process.env.NV_PASSWORD || 'nidavellir');
    await page.getByRole('button', {name: 'Sign in'}).click();

    for (const theme of ['day', 'night']) {
      await page.evaluate(t => localStorage.setItem('nidavellir-theme', t), theme);
      await page.goto(live);
      await page.locator('.fg-svg .fg-ev').first().waitFor();
      assert.equal(await overflow(), false, `live view scrolls sideways (${theme})`);
      await shot(`forge-line-${theme}`);
    }
    await page.evaluate(() => localStorage.setItem('nidavellir-theme', 'day'));
    await page.goto(live);
    await page.locator('.fg-svg .fg-ev').first().waitFor();

    // Timeline is the default view; the spine, strands, marks and folds render.
    const view = page.getByRole('group', {name: 'View'});
    assert.equal(await view.getByRole('button', {name: 'Timeline'}).getAttribute('aria-pressed'), 'true');
    const heads = await page.locator('.fg-head .h1').allTextContents();
    assert.ok(heads.includes('claude-attacker') && heads.includes('gpt-defender'), `strands: ${heads}`);
    const marks = await page.locator('.fg-ev').count();
    assert.ok(marks > 100, `${marks} steps drawn`);
    assert.ok(await page.locator('.fg-knot').count() > 0, 'failure knots drawn');
    assert.ok(await page.locator('.fg-fruit').count() >= 2, 'finding marks drawn on the spine');
    assert.ok(await page.locator('.fg-model').count() > 0, 'model rings drawn');
    assert.ok(await page.locator('.fg-gap').count() >= 1, 'the idle stretch folds into one line');
    assert.match(await page.locator('.fg-gap').first().textContent(), /min with nothing running/);
    checks.push(`timeline by default: 2 strands, ${marks} steps, failure knots, finding marks, model rings, a folded silence`);

    // Hover previews; click pins the step in the inspector.
    const step = page.locator('.fg-ev').filter({has: page.locator('.fg-pill')}).nth(40);
    await step.scrollIntoViewIfNeeded();
    await step.hover({force: true});
    await page.locator('.fg-tip').waitFor();
    const tipName = (await page.locator('.fg-tip b').textContent()).trim();
    await step.click({force: true});
    assert.equal(await step.getAttribute('class').then(c => c.includes('sel')), true);
    assert.match(await page.locator('.live-inspector').innerText(), new RegExp(tipName.replace('/', '\\/')));
    checks.push(`hover previews "${tipName}"; click pins it in the inspector`);

    // Arrow keys move the selection inside the timeline.
    await page.locator('.fg-line-scroll').focus();
    const before = await page.locator('.fg-ev.sel').count();
    await page.keyboard.press('ArrowUp');
    assert.equal(before, 1);
    assert.equal(await page.locator('.fg-ev.sel').count(), 1);
    checks.push('arrow keys move the selection on the timeline');

    // Filters narrow what is drawn.
    await page.getByLabel('Kind').selectOption('model');
    const models = await page.locator('.fg-ev').count();
    assert.ok(models > 0 && models < marks, `kind=model draws ${models} of ${marks}`);
    assert.equal(await page.locator('.fg-pill').count(), 0, 'no tool pills under kind=model');
    await page.getByLabel('Kind').selectOption('');
    checks.push(`filters narrow the timeline (model only: ${models} of ${marks})`);

    // Replay: the scrubber rewinds; Back to live shows everything again.
    const scrub = page.getByLabel('Scrub through the run');
    const min = Number(await scrub.getAttribute('min'));
    await scrub.fill(String(min + 400));
    await page.waitForFunction(() => document.querySelectorAll('.fg-ev.fut').length > 0);
    const hidden = await page.locator('.fg-ev.fut').count();
    await page.getByRole('button', {name: 'Replay'}).click();
    const clock0 = await page.locator('.fg-clock').textContent();
    await page.waitForFunction(c => document.querySelector('.fg-clock').textContent !== c, clock0);
    await page.getByRole('button', {name: 'Pause replay'}).click();
    await page.getByRole('button', {name: 'Back to live'}).click();
    await page.waitForFunction(() => document.querySelectorAll('.fg-ev.fut').length === 0);
    checks.push(`replay: scrubbing back hides ${hidden} later steps, Replay advances the clock, Back to live restores all`);

    // The list view keeps every step, the waterfall and keyboard navigation.
    await view.getByRole('button', {name: 'List'}).click();
    await page.locator('.live-row[role="option"]').first().waitFor();
    assert.ok(await page.locator('.live-list[role="listbox"]').isVisible());
    assert.equal(await page.locator('.fg-svg').count(), 0);
    checks.push('the List view still lists every step with the waterfall');
    await view.getByRole('button', {name: 'Timeline'}).click();
    await page.locator('.fg-svg').waitFor();

    // Phone width.
    await page.setViewportSize({width: 390, height: 844});
    await page.goto(live);
    await page.locator('.fg-svg .fg-ev').first().waitFor();
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
