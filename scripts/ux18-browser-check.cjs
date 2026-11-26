// UX-18 browser check: findings you open in place, across arenas and per
// arena. Against a mock stack with one arena holding operator findings rated
// critical, high, low and info (plus older unrated ones).
// NV_UX18_CONFIG: {"arena", "critical", "high"} (arena id, two finding ids).
const assert = require('node:assert/strict');
const fs = require('node:fs');
const {chromium} = require(process.env.NV_PLAYWRIGHT_MODULE || 'playwright');
const config = JSON.parse(fs.readFileSync(process.env.NV_UX18_CONFIG, 'utf8'));
const WEB = process.env.NV_WEB || 'http://127.0.0.1:15020';
const SHOTS = process.env.NV_UX18_SHOTS || '';

(async () => {
  const browser = await chromium.launch({headless: true,
    executablePath: process.env.NV_CHROMIUM_PATH || undefined, args: ['--no-sandbox']});
  const page = await (await browser.newContext({viewport: {width: 1440, height: 1000}})).newPage();
  const errors = []; page.on('pageerror', error => errors.push(String(error)));
  const checks = [];
  const shot = async name => SHOTS && page.screenshot({path: `${SHOTS}/${name}.png`, fullPage: true});
  const overflow = () => page.evaluate(() => document.documentElement.scrollWidth > window.innerWidth + 1);
  const row = id => page.locator(`#finding-${id}`);
  try {
    await page.goto(`${WEB}/console/findings`);
    await page.getByLabel('Username').fill(process.env.NV_USER || 'admin');
    await page.getByLabel('Password').fill(process.env.NV_PASSWORD || 'nidavellir');
    await page.getByRole('button', {name: 'Sign in'}).click();
    await page.locator('.fl-row').first().waitFor();
    assert.equal(await page.locator('.rail-nav [aria-current="page"]').innerText(), 'Findings');

    // Severity tiles count and filter; a second click clears.
    const tiles = page.getByRole('group', {name: 'Filter by severity'});
    const critical = tiles.getByRole('button', {name: /Critical/});
    const total = await page.locator('.fl-row').count();
    await critical.click();
    assert.equal(await critical.getAttribute('aria-pressed'), 'true');
    const rows = await page.locator('.fl-row').count();
    assert.ok(rows >= 1 && rows < total, `critical filter shows ${rows} of ${total}`);
    assert.ok(await row(config.critical).isVisible());
    assert.equal(await page.locator('.fl-row .sev').evaluateAll(els => els.every(e => e.textContent === 'Critical')), true);
    await critical.click();
    assert.equal(await page.locator('.fl-row').count(), total);
    checks.push(`severity tiles filter (${rows} critical of ${total}) and a second click clears`);

    // Critical sorts first; decision filter.
    assert.equal(await page.locator('.fl-row .sev').first().textContent(), 'Critical');
    const decision = page.getByRole('group', {name: 'Filter by decision'});
    await decision.getByRole('button', {name: 'Decided'}).click();
    const decided = await page.locator('.fl-row').count();
    await decision.getByRole('button', {name: 'Awaiting you'}).click();
    const awaiting = await page.locator('.fl-row').count();
    assert.equal(decided + awaiting, total);
    await decision.getByRole('button', {name: 'All'}).click();
    checks.push(`rows sort by severity; decision filter splits ${awaiting} awaiting + ${decided} decided = ${total}`);

    // Open in place by mouse and by keyboard.
    const sum = row(config.critical).locator('.fl-sum');
    await sum.click();
    assert.equal(await sum.getAttribute('aria-expanded'), 'true');
    const body = row(config.critical).locator('.fl-body');
    await body.getByText('What the reporter claims').waitFor();
    await body.getByText('The q parameter reaches the query unescaped.').waitFor();
    assert.match(await body.locator('.fl-poc').innerText(), /curl/);
    await body.getByText('What the validator saw').waitFor();
    assert.match(await body.locator('.fl-kv').innerText(), /Critical \(reporter's rating\)/);
    await body.getByRole('link', {name: 'Open in arena'}).waitFor();
    await shot('findings-open');
    await sum.focus();
    await page.keyboard.press('Enter');
    assert.equal(await sum.getAttribute('aria-expanded'), 'false');
    await page.keyboard.press('Space');
    assert.equal(await sum.getAttribute('aria-expanded'), 'true');
    checks.push('a row opens in place by click, Enter and Space, showing claim, reproduction, validator and the rating as a claim');

    // "Open in arena" lands on the arena tab with that finding open.
    await body.getByRole('link', {name: 'Open in arena'}).click();
    await page.waitForURL(new RegExp(`tab=findings&finding=${config.critical}`));
    const arenaRow = row(config.critical);
    await arenaRow.locator('.fl-body').waitFor();
    assert.equal(await arenaRow.locator('.fl-sum').getAttribute('aria-expanded'), 'true');
    await arenaRow.getByRole('button', {name: 'Confirm with evidence'}).waitFor();
    assert.equal(await arenaRow.getByRole('button', {name: 'Refute'}).isDisabled(), true);
    await arenaRow.getByText(/Refuting needs the control and evidence review/).waitFor();
    await arenaRow.getByText('Review controls and evidence').waitFor();
    await shot('arena-findings');
    checks.push('Open in arena deep-links ?finding=<id>: the row arrives open with Confirm, and Refute disabled with its reason');

    // The operator's own report form offers a severity.
    const form = page.locator('details.finding-record');
    await form.locator(':scope > summary').click();
    const options = await form.locator('select[name="severity"] option').allInnerTexts();
    assert.deepEqual(options, ['Not rated', 'Critical', 'High', 'Medium', 'Low', 'Info']);
    checks.push('the operator report form offers Not rated plus the five levels');

    // Themes and phone width.
    for (const theme of ['day', 'night']) {
      await page.evaluate(t => localStorage.setItem('nidavellir-theme', t), theme);
      await page.goto(`${WEB}/console/findings?finding=${config.high}`);
      await row(config.high).locator('.fl-body').waitFor();
      assert.equal(await overflow(), false, `findings scroll sideways (${theme})`);
      await shot(`findings-${theme}`);
    }
    await page.evaluate(() => localStorage.setItem('nidavellir-theme', 'day'));
    await page.setViewportSize({width: 390, height: 844});
    for (const url of [`${WEB}/console/findings?finding=${config.high}`,
      `${WEB}/console/arena/${config.arena}?tab=findings&finding=${config.critical}`]) {
      await page.goto(url);
      await page.locator('.fl-body').first().waitFor();
      assert.equal(await overflow(), false, `${url} scrolls sideways at 390 px`);
    }
    checks.push('both themes render; neither page scrolls sideways at 390 px');

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
