// UX-24 browser check: a finding as a report you can send. Against a mock
// stack with one research arena holding a report-shaped finding (hypothesis
// contract and test note, PoC, causality, HTTP evidence) and a bare one.
// NV_UX24_CONFIG: {"arena", "rich", "bare"}.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const {chromium} = require(process.env.NV_PLAYWRIGHT_MODULE || 'playwright');
const config = JSON.parse(fs.readFileSync(process.env.NV_UX24_CONFIG, 'utf8'));
const WEB = process.env.NV_WEB || 'http://127.0.0.1:15020';
const SHOTS = process.env.NV_UX24_SHOTS || '';

(async () => {
  const browser = await chromium.launch({headless: true,
    executablePath: process.env.NV_CHROMIUM_PATH || undefined, args: ['--no-sandbox']});
  const context = await browser.newContext({viewport: {width: 1440, height: 1000}});
  await context.grantPermissions(['clipboard-read', 'clipboard-write'], {origin: WEB});
  const page = await context.newPage();
  const errors = []; page.on('pageerror', error => errors.push(String(error)));
  const checks = [];
  const shot = async name => SHOTS && page.screenshot({path: `${SHOTS}/${name}.png`, fullPage: true});
  const url = id => `${WEB}/console/arena/${config.arena}?tab=findings&finding=${id}`;
  const clipboard = () => page.evaluate(() => navigator.clipboard.readText());
  try {
    await page.goto(url(config.rich));
    await page.getByLabel('Username').fill(process.env.NV_USER || 'admin');
    await page.getByLabel('Password').fill(process.env.NV_PASSWORD || 'nidavellir');
    await page.getByRole('button', {name: 'Sign in'}).click();
    const row = page.locator(`#finding-${config.rich}`);
    await row.locator('.fl-body').waitFor();

    // Awaiting a decision: the row opens on the review; Report is one click.
    const views = row.getByRole('group', {name: 'Finding view'});
    assert.equal(await views.getByRole('button', {name: 'Review'}).getAttribute('aria-pressed'), 'true');
    await views.getByRole('button', {name: 'Report'}).click();
    const report = row.locator('.fr');
    await report.locator('.fr-section').first().waitFor();
    const titles = await report.locator('.fr-section h3').allTextContents();
    assert.deepEqual(titles.map(t => t.trim().toLowerCase()), ['summary', 'impact', 'description',
      'prerequisites', 'steps to reproduce', 'proof', 'remediation', 'references']);
    const section = key => report.locator('.fr-section').filter({has: page.getByRole('heading', {name: key, exact: true})});
    assert.match(await section('Description').innerText(), /Static export must never write/);
    assert.match(await section('Prerequisites').innerText(), /WORKPLACE_USER/);
    assert.match(await section('Proof').innerText(), /Hypothesis H-F1 supported/);
    assert.equal(await section('Impact').locator('.fr-origin.missing').count(), 1);
    assert.match(await report.locator('.fr-ready').innerText(), /4 gaps before sending/);
    await shot('report-gaps');
    checks.push('the report assembles description, prerequisites and proof from the hypothesis and evidence; 4 gaps are named');

    // Write what only the operator can say; the gaps close except verification.
    await report.getByRole('button', {name: 'Edit write-up'}).click();
    const form = report.getByRole('form', {name: 'Edit write-up'});
    await form.getByLabel('Product', {exact: true}).fill('Example CMS');
    await form.getByLabel('Affected versions', {exact: true}).fill('22.0');
    await form.getByLabel('Vendor', {exact: true}).fill('Example Vendor');
    await form.getByLabel('CVSS 3.1 vector', {exact: true}).fill('CVSS:3.1/AV:N/AC:L/PR:L/UI:N/S:U/C:H/I:H/A:H');
    await form.getByRole('textbox', {name: /^Impact /}).fill('A workplace author runs code as the CMS service user.');
    await form.getByRole('textbox', {name: /^Remediation /}).fill('Refuse every JSP-mapped extension in the static export.');
    await form.getByRole('button', {name: 'Add reference'}).click();
    await form.getByLabel('Reference 1 URL').fill('https://example.org/advisory');
    await form.getByLabel('Reference 1 title').fill('Vendor advisory');
    await form.getByRole('button', {name: 'Save write-up'}).click();
    await report.locator('.fr-editor').waitFor({state: 'detached'});
    assert.match(await report.locator('.fr-ready').innerText(), /1 gap before sending/);
    assert.equal(await section('Impact').locator('.fr-origin.operator').count(), 1);
    assert.match(await report.locator('.fr-meta').innerText(), /Write-up by \S+/);
    checks.push('saving the write-up fills impact, remediation, product and versions; only technical verification remains');

    // Copy as Markdown and as a CVE request; download the .md file.
    await report.getByRole('button', {name: 'Copy report'}).click();
    await report.getByText('Report copied as Markdown').waitFor();
    const md = await clipboard();
    assert.ok(md.startsWith('# Static export runs an uploaded .jspf'), md.slice(0, 80));
    for (const part of ['| Product | Example CMS |', '## Impact\n\nA workplace author', '## Steps to reproduce',
      '- [Vendor advisory](https://example.org/advisory)', '| Severity | High (CVSS:3.1/'])
      assert.ok(md.includes(part), part);
    await report.getByRole('button', {name: 'Copy CVE request'}).click();
    await report.getByText('CVE request copied').waitFor();
    const cve = await clipboard();
    assert.ok(cve.includes('[Affected product code base]\nExample CMS 22.0'));
    assert.ok(cve.includes('[Impact]\nCode execution'));
    const download = page.waitForEvent('download');
    await report.getByRole('link', {name: '.md'}).click();
    assert.match((await download).suggestedFilename(), new RegExp(`finding-${config.rich}\\.md`));
    checks.push('Copy report puts the Markdown on the clipboard, Copy CVE request the form fields, and .md downloads the file');
    await shot('report-ready');

    // A bare finding: the report says what is missing instead of inventing it.
    await page.goto(url(config.bare));
    const bare = page.locator(`#finding-${config.bare}`);
    await bare.getByRole('group', {name: 'Finding view'}).getByRole('button', {name: 'Report'}).click();
    await bare.locator('.fr-section').first().waitFor();
    assert.ok(await bare.locator('.fr-section.missing').count() >= 4);
    assert.match(await bare.locator('.fr-ready').innerText(), /gaps before sending/);
    checks.push('a bare finding shows its missing sections and gaps, nothing invented');

    // Phone width.
    await page.setViewportSize({width: 390, height: 844});
    await page.goto(url(config.rich));
    await page.locator(`#finding-${config.rich}`).getByRole('button', {name: 'Report'}).click();
    await page.locator('.fr-section').first().waitFor();
    assert.equal(await page.evaluate(() => document.documentElement.scrollWidth > window.innerWidth + 1), false);
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
