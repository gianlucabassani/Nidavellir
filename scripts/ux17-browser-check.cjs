// UX-17 browser check: the arena dashboard and the Research overview.
// Against a mock stack with one seeded arena that has a realistic run (spans
// over ~80 minutes with failures, findings, a refusal and budget spend), one
// agent bound to it, and one arena with no activity.
// NV_UX17_CONFIG: {"arena", "empty", "spent"}.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const {chromium} = require(process.env.NV_PLAYWRIGHT_MODULE || 'playwright');
const config = JSON.parse(fs.readFileSync(process.env.NV_UX17_CONFIG, 'utf8'));
const WEB = process.env.NV_WEB || 'http://127.0.0.1:15020';
const SHOTS = process.env.NV_UX17_SHOTS || '';

(async () => {
  const browser = await chromium.launch({headless: true,
    executablePath: process.env.NV_CHROMIUM_PATH || undefined, args: ['--no-sandbox']});
  const page = await (await browser.newContext({viewport: {width: 1440, height: 1000}})).newPage();
  const errors = []; page.on('pageerror', error => errors.push(String(error)));
  const checks = [];
  const shot = async name => SHOTS && page.screenshot({path: `${SHOTS}/${name}.png`, fullPage: true});
  const overflow = () => page.evaluate(() => document.documentElement.scrollWidth > window.innerWidth + 1);
  const arena = `${WEB}/console/arena/${config.arena}?tab=forge`;
  try {
    await page.goto(arena);
    await page.getByLabel('Username').fill(process.env.NV_USER || 'admin');
    await page.getByLabel('Password').fill(process.env.NV_PASSWORD || 'nidavellir');
    await page.getByRole('button', {name: 'Sign in'}).click();

    for (const theme of ['day', 'night']) {
      await page.evaluate(t => localStorage.setItem('nidavellir-theme', t), theme);
      await page.goto(arena);
      await page.locator('.dash .act-col').first().waitFor();
      assert.equal(await overflow(), false, `dashboard scrolls sideways (${theme})`);
      await shot(`dashboard-${theme}`);
    }
    await page.evaluate(() => localStorage.setItem('nidavellir-theme', 'day'));
    await page.goto(arena);
    await page.locator('.dash .act-col').first().waitFor();

    // Header: identity, budget used, the actions an operator reaches for.
    const head = page.locator('.arena-head');
    await head.getByRole('heading', {level: 1}).waitFor();
    assert.match(await head.innerText(), new RegExp(`${config.spent} / 1000`));
    for (const name of ['Extend time', 'Stop research', 'More'])
      await head.getByRole('button', {name}).waitFor();
    checks.push(`header shows the arena, ${config.spent}/1000 actions used, Extend, Stop and More`);

    // One-line status from the recorded spans.
    const say = await page.locator('.dash-say').innerText();
    assert.match(say, /^Running steadily\. [\d,]+ actions in \d+ h \d+ min, \d+ failed \([\d.]+%\), 1 refused\. \d+ findings?/);
    checks.push(`status sentence: "${say.slice(0, 90)}…"`);

    // Activity chart: columns, tooltip on keyboard focus, table view.
    const cols = page.locator('.dash .act-col');
    const count = await cols.count();
    assert.ok(count >= 12 && count <= 24, `activity has ${count} intervals`);
    await cols.nth(count - 4).focus();
    const tip = page.locator('.dash .act-col .chart-tip');
    await tip.waitFor();
    assert.match(await tip.innerText(), /actions/);
    assert.match(await cols.nth(count - 4).getAttribute('aria-label'), /actions/);
    assert.ok(await page.locator('.dash .act-fail').count() > 0, 'failure marks drawn');
    assert.ok(await page.locator('.dash .act-marks .mk-find').count() >= 2, 'finding marks drawn');
    const activityCard = page.locator('.dash-main').first().locator('.panel').first();
    await activityCard.getByRole('button', {name: 'Show table'}).click();
    assert.equal(await activityCard.locator('.chart-table tbody tr').count(), count);
    await activityCard.getByRole('button', {name: 'Show chart'}).click();
    checks.push(`activity: ${count} intervals stacked by kind, failure and finding marks, tooltip on focus, table view with ${count} rows`);

    // Budget burn with projection, by-kind bars, outcomes.
    const budget = page.locator('.dash-main').first().locator('.panel').nth(1);
    assert.match(await budget.innerText(), new RegExp(`${config.spent} of 1,000 actions`));
    await budget.locator('.burn-limit').waitFor({state: 'attached'});
    // A run that has gone quiet has no pace to project, and says so.
    const say2 = await budget.locator('.chart-say').innerText();
    if (await budget.locator('.burn-proj').count())
      assert.match(say2, /actions\/min the budget/);
    else assert.match(say2, /no projection|exhausted/i);
    const bars = await page.locator('.dash-three .bars-name').allInnerTexts();
    assert.deepEqual(bars.map(t => t.trim()), ['HTTP', 'Shell', 'Model', 'Other']);
    assert.match(await page.locator('.dash-three .share-legend').innerText(), /Refused by policy or budget\s+1/);
    checks.push('budget burn draws the limit and a labelled projection; by-kind bars and outcomes (1 refused) render');

    // Stations as built, agents here, recent steps newest first.
    assert.ok(await page.locator('.stn').count() >= 1);
    await page.locator('.dash-agents').getByText('claude-attacker').first().waitFor();
    const times = await page.locator('.dash-table tbody tr td:first-child').allInnerTexts();
    assert.ok(times.length > 0 && times.length <= 8);
    assert.deepEqual([...times].sort().reverse(), times, 'recent steps newest first');
    checks.push(`stations, the bound agent and ${times.length} recent steps (newest first) render`);

    // Extend time through the BFF.
    await head.getByRole('button', {name: 'Extend time'}).click();
    await head.getByRole('menuitem', {name: 'Add 30 minutes'}).click();
    await head.getByText('Extended by 30 minutes.').waitFor();
    checks.push('Extend time → Add 30 minutes succeeds and says so');

    // An arena with no activity explains itself instead of drawing empty charts.
    await page.goto(`${WEB}/console/arena/${config.empty}?tab=forge`);
    await page.getByText('Charts appear with the first action').waitFor();
    assert.equal(await page.locator('.dash .act').count(), 0);
    checks.push('an arena with no activity shows why there are no charts');

    // Research overview.
    for (const theme of ['day', 'night']) {
      await page.evaluate(t => localStorage.setItem('nidavellir-theme', t), theme);
      await page.goto(`${WEB}/console?workspace=research`);
      await page.locator('.ov-kpis').waitFor();
      await page.locator('.ov-row .act-col').first().waitFor();
      assert.equal(await overflow(), false, `overview scrolls sideways (${theme})`);
      await shot(`overview-${theme}`);
    }
    await page.evaluate(() => localStorage.setItem('nidavellir-theme', 'day'));
    assert.equal(await page.locator('.ov-kpi').count(), 4);
    await page.locator('.ov-agent').filter({hasText: 'claude-attacker'}).filter({hasText: 'juice-authz'}).first().waitFor();
    const heights = await page.evaluate(() => [...document.querySelectorAll('.ov-main')[0].children]
      .map(el => Math.round(el.getBoundingClientRect().height)));
    assert.equal(heights[0], heights[1], `Agents now and Needs attention are equal height (${heights})`);
    // The last hour may be quiet on a reused stack; then the card says so.
    if (!(await page.locator('.ov-row .bars-name').count()))
      await page.getByText('No one acted in the last hour').waitFor();
    assert.ok(await page.locator('.ov-table tbody tr').count() >= 2);
    checks.push(`overview: agents now and needs attention side by side at equal height (${heights[0]} px), 4 KPIs, last-hour chart, who did the work, arenas`);

    // Phone width.
    await page.setViewportSize({width: 390, height: 844});
    for (const url of [`${WEB}/console?workspace=research`, arena]) {
      await page.goto(url);
      await page.locator('#main h1').first().waitFor();
      await page.waitForTimeout(300);
      assert.equal(await overflow(), false, `${url} scrolls sideways at 390 px`);
    }
    checks.push('neither page scrolls sideways at 390 px');

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
