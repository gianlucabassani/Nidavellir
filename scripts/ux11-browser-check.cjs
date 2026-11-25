// UX-11/UX-12 browser check: evaluation dashboard, live push update, trial
// comparison and suite history, against a mock stack seeded with an NV-08-shaped
// five-seed suite (baseline with the HTTP tool, candidate without it).
// NV_UX11_CONFIG: {"first","second","live","suite"} ids; NV_UX11_FINISH_CMD: a
// shell command that finishes one queued trial of the live evaluation.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const {execSync} = require('node:child_process');
const {chromium} = require(process.env.NV_PLAYWRIGHT_MODULE || 'playwright');
const config = JSON.parse(fs.readFileSync(process.env.NV_UX11_CONFIG, 'utf8'));
const WEB = process.env.NV_WEB || 'http://127.0.0.1:15020';
const SHOTS = process.env.NV_UX11_SHOTS || '';
(async () => {
  const browser = await chromium.launch({headless: true,
    executablePath: process.env.NV_CHROMIUM_PATH || undefined, args: ['--no-sandbox']});
  const page = await (await browser.newContext({viewport: {width: 1440, height: 1000}})).newPage();
  const errors = []; page.on('pageerror', error => errors.push(String(error)));
  const checks = [];
  const shot = async name => SHOTS && page.screenshot({path: `${SHOTS}/${name}.png`, fullPage: true});
  try {
    await page.goto(`${WEB}/console/evaluations/${config.first}`);
    await page.getByLabel('Username').fill(process.env.NV_USER || 'admin');
    await page.getByLabel('Password').fill(process.env.NV_PASSWORD || 'nidavellir');
    await page.getByRole('button', {name: 'Sign in'}).click();
    await page.getByRole('heading', {name: 'Evaluation result'}).waitFor();

    // FR-16: the plot labels its interval; a degenerate one has no bar.
    const plots = page.locator('svg.diff-plot');
    assert.ok(await plots.count() >= 1);
    const verified = await page.locator('svg.diff-plot[aria-label^="Verified findings"]').getAttribute('aria-label');
    assert.match(verified, /Degenerate/);
    assert.equal(await page.locator('svg.diff-plot[aria-label^="Verified findings"] .diff-interval').count(), 0);
    checks.push('Degenerate verified-findings interval is labelled and drawn without a bar');

    // Grid: 5 seeds × 2 sides; the infrastructure-failed cell has no score mark.
    const grid = page.getByRole('table', {name: 'Outcome by challenge, seed and side'});
    assert.equal(await grid.locator('tbody tr').count(), 5);
    const infra = grid.locator('.outcome-infra');
    assert.equal(await infra.count(), 1);
    assert.equal((await infra.innerText()).includes('✓') || (await infra.innerText()).includes('✕'), false);
    assert.ok(await grid.locator('a.outcome-pass[href^="/console/arena/"]').count() >= 4);
    checks.push('Outcome grid: 5 seeds, cells link to trial timelines, infrastructure failure has no score mark');
    const tokens = await page.locator('svg[aria-label^="Model tokens, candidate"]').getAttribute('aria-label');
    assert.match(tokens, /4 trials/);
    checks.push('Token distribution excludes the infrastructure-failed trial');
    await shot('ux11-dashboard');

    // FR-17: the candidate never issues the request the baseline used.
    const started = Date.now(); let clicks = 0;
    await grid.locator('tbody tr').first().getByRole('link', {name: 'Compare'}).click(); clicks++;
    await page.getByRole('heading', {name: 'Trial comparison'}).waitFor();
    await page.getByText('B never called:').waitFor();
    assert.match(await page.locator('.compare-tools').innerText(), /http\/request/);
    const divergence = page.locator('tr.compare-divergence');
    assert.equal(await divergence.count(), 1);
    assert.match(await divergence.innerText(), /first divergence/i);
    assert.match(await divergence.innerText(), /http\/request/);
    assert.match(await divergence.innerText(), /never issued by the other run/);
    assert.match(await page.locator('.compare-findings').innerText(), /Admin panel without authorization/);
    checks.push(`Comparison reached in ${clicks} click (${Date.now() - started} ms): divergence at the HTTP request, candidate never issued it, findings and verdicts shown`);
    await shot('ux12-compare');

    // History: flaky seed and calibration-only series.
    await page.goto(`${WEB}/console/suites/${config.suite}/history`);
    await page.getByRole('heading', {name: 'Suite history'}).waitFor();
    assert.match(await page.locator('main').innerText(), /not held-out capability/);
    assert.equal(await page.getByText('Held-out outcome over time').count(), 0);
    assert.ok(await page.getByRole('table', {name: 'Flaky cells'}).locator('tbody tr').count() >= 1);
    checks.push('Suite history: calibration series only, flaky seed listed');
    await shot('ux11-history');

    // Live: progress changes without a reload, pushed by the evaluation stream.
    await page.goto(`${WEB}/console/evaluations/${config.live}`);
    await page.getByRole('heading', {name: 'Evaluation progress'}).waitFor();
    const before = await page.locator('.result-progress strong').innerText();
    let reloaded = false; page.on('framenavigated', frame => { if (frame === page.mainFrame()) reloaded = true; });
    await page.waitForTimeout(1500);
    const t0 = Date.now();
    execSync(process.env.NV_UX11_FINISH_CMD, {stdio: 'inherit'});
    await page.waitForFunction(text => document.querySelector('.result-progress strong')?.textContent !== text,
      before, {timeout: 10000});
    assert.equal(reloaded, false);
    checks.push(`Live progress updated without reload in ${Date.now() - t0} ms ("${before}" → "${await page.locator('.result-progress strong').innerText()}")`);

    assert.deepEqual(errors, []);
    console.log(JSON.stringify({ok: true, checks}, null, 1));
  } catch (error) {
    await shot('ux11-failure');
    console.log(JSON.stringify({ok: false, checks, errors, error: String(error)}, null, 1));
    process.exitCode = 1;
  } finally {
    await browser.close();
  }
})();
