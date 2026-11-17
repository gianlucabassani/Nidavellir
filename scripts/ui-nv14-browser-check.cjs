// NV-14 console journey: campaign list, one campaign, finding group drawer,
// disclosure state, bundle generation and download, reflow and keyboard.
//
// Needs a running console + service where NV_14_FINDING is a finding whose group
// has a confirmed and a refuted member, and NV_14_SINGLE is a finding with no
// variant. It creates campaigns, disclosure states and bundles; run it only
// against a disposable instance.
//
//   NV_PLAYWRIGHT_MODULE=/path/to/node_modules/playwright NV_CHROMIUM_PATH=/path/to/chromium \
//   NV_14_WEB=http://127.0.0.1:15082 NV_14_PASSWORD=... NV_14_FINDING=<12 hex> \
//   NV_14_SINGLE=<12 hex> NV_14_OUT=/path/to/output-dir node scripts/ui-nv14-browser-check.cjs
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const { chromium } = require(process.env.NV_PLAYWRIGHT_MODULE || 'playwright');

const WEB = process.env.NV_14_WEB || 'http://127.0.0.1:15082';
const USER = process.env.NV_14_USER || 'admin';
const PASSWORD = process.env.NV_14_PASSWORD || '';
const FINDING = process.env.NV_14_FINDING || '';
const SINGLE = process.env.NV_14_SINGLE || '';
const OUT = process.env.NV_14_OUT || '.';
const NAME = process.env.NV_14_NAME || 'Browser check campaign';
const PRODUCT = process.env.NV_14_PRODUCT || 'calibration target';
const CAPTION =
  'Disclosure state is operator judgment; the outcome column is what the recorded evidence shows.';
const STANDING = 'nothing here establishes that other versions are unaffected';
const WIDTHS = [320, 390, 1440];
// Words the views must never use about a version or a finding.
const CLAIMS = /\b(safe|secure|not vulnerable|unaffected|no vulnerabilit|exhaust)/i;

(async () => {
  assert.match(FINDING, /^[0-9a-f]{12}$/);
  const browser = await chromium.launch({
    headless: true,
    executablePath: process.env.NV_CHROMIUM_PATH || undefined,
    args: ['--no-sandbox'],
  });
  const context = await browser.newContext({ viewport: { width: 1440, height: 900 }, acceptDownloads: true });
  const page = await context.newPage();
  const errors = [];
  page.on('pageerror', (error) => errors.push(String(error)));
  const report = { date: new Date().toISOString(), web: WEB, checks: [], reflow: [] };
  const check = (text) => report.checks.push(text);
  const rows = () => page.locator('.campaign-findings tbody tr');
  const drawer = () => page.locator('dialog.source-review-drawer');

  async function login() {
    await page.getByLabel('Username').fill(USER);
    await page.getByLabel('Password').fill(PASSWORD);
    await page.getByRole('button', { name: 'Sign in' }).click();
  }
  async function noHorizontalScroll(label) {
    for (const width of WIDTHS) {
      await page.setViewportSize({ width, height: 900 });
      await page.waitForTimeout(150);
      const size = await page.evaluate(() => ({
        scroll: document.documentElement.scrollWidth,
        client: document.documentElement.clientWidth,
      }));
      report.reflow.push({ view: label, width, ...size });
      assert.ok(size.scroll <= size.client, `${label} scrolls sideways at ${width}px: ${size.scroll} > ${size.client}`);
      await page.screenshot({ path: path.join(OUT, `ui-nv14-${label}-${width}.png`), fullPage: false });
    }
    await page.setViewportSize({ width: 1440, height: 900 });
  }
  async function addFinding(id) {
    await page.getByLabel('Finding id').fill(id);
    await page.getByRole('button', { name: 'Add finding group' }).click();
  }
  async function openRow(index) {
    await rows().nth(index).locator('th button').click();
    await drawer().waitFor();
    return drawer();
  }
  async function closeDrawer() {
    await drawer().getByRole('button', { name: 'Close', exact: true }).click();
    await drawer().waitFor({ state: 'detached' });
  }
  async function saveState(label, note, reference) {
    await drawer().getByLabel(label, { exact: true }).check();
    await drawer().getByLabel('Note', { exact: false }).fill(note || '');
    await drawer().getByLabel('Reference', { exact: false }).fill(reference || '');
    await drawer().getByRole('button', { name: 'Save disclosure state' }).click();
  }

  try {
    fs.mkdirSync(OUT, { recursive: true });
    await page.goto(`${WEB}/console/research/campaigns`);
    await login();
    await page.getByRole('heading', { name: 'Campaigns', exact: true }).first().waitFor();
    assert.ok((await page.locator('.source-review-caption').innerText()).includes(CAPTION));
    check('Unauthenticated visit was sent to login; the campaign list loaded after sign-in');

    // --- create ---------------------------------------------------------------
    await page.getByRole('button', { name: 'New campaign', exact: true }).click();
    await noHorizontalScroll('new-campaign');
    await page.getByLabel('Campaign name').fill(NAME);
    await page.getByLabel('Product').fill(PRODUCT);
    await page.getByLabel('Note (optional)').fill('Created by the browser check.');
    await page.getByRole('button', { name: 'Create campaign' }).click();
    await page.waitForURL(/\/console\/research\/campaigns\/[0-9a-f]{32}$/);
    const campaignUrl = page.url();
    const banner = page.locator('.source-review-banner');
    await banner.waitFor();
    assert.match(await banner.innerText(), /Limits of this campaign/);
    assert.equal(await banner.locator('button, a, summary, input').count(), 0);
    check('A campaign was created; its page shows the standing limits note with no control to dismiss it');

    // --- one row per finding group --------------------------------------------
    await addFinding('not-a-finding');
    assert.match(await page.locator('.campaign-add [role=alert]').innerText(), /12 lowercase hex/);
    await addFinding(FINDING);
    await page.locator('.campaign-add [role=status]').getByText(/Added finding group/).waitFor();
    await rows().first().waitFor();
    assert.equal(await rows().count(), 1);
    await addFinding(FINDING);
    await page.locator('.campaign-add [role=status]').getByText(/already in this campaign; nothing changed/).waitFor();
    assert.equal(await rows().count(), 1);
    const first = await rows().first().innerText();
    assert.match(first, /Disappeared under controls/);
    assert.match(first, /Affected 1/);
    assert.match(first, /Not observed under controls 1/);
    assert.match(first, /unknown 0/i);
    assert.match(first, /Internal/);
    assert.equal(await page.locator('.campaign-findings caption').innerText(), CAPTION);
    check('Adding a finding added its group as one row; adding it again changed nothing; the row shows the evidence outcome beside the disclosure state');

    // --- drawer: identities, state, history -------------------------------------
    await openRow(0);
    let text = await drawer().innerText();
    assert.ok(text.includes(CAPTION));
    assert.match(text, /Evidence outcome/i);
    assert.match(text, /Operator disclosure state/i);
    assert.match(text, /Affected \(1\)/);
    assert.match(text, /Not observed under controls \(1\)/);
    assert.match(text, /Unknown \(0\)/);
    assert.match(text, /A version that was not run is not listed anywhere\./);
    assert.match(text, /Evidence cannot speak to this state/);
    check('The drawer lists identities by verdict and says that a version that was not run is not listed');

    await saveState('Regressed', '', '');
    assert.match(await drawer().getByRole('alert').innerText(), /at least 10 characters/);
    await saveState('Reported', 'Reported to the maintainers privately.', 'GHSA-demo');
    await drawer().getByText('Recorded as reported.').waitFor();
    await saveState('Fixed', 'Fixed upstream in the next release.', '');
    await drawer().getByText('Recorded as fixed.').waitFor();
    text = await drawer().innerText();
    assert.match(text, /Supported by recorded evidence/);
    const history = await drawer().locator('.source-review-history').first().innerText();
    assert.match(history, /Fixed[\s\S]*Fixed upstream[\s\S]*Reported[\s\S]*Reference: GHSA-demo/);
    check('Regressed without a note was refused in the form; reported then fixed were recorded, with both entries in the history; fixed is shown as supported by the evidence');

    // --- bundle -------------------------------------------------------------------
    await drawer().getByRole('button', { name: 'Generate bundle' }).click();
    await drawer().getByText(/Bundle sha256:[0-9a-f]{12}… generated\./).waitFor();
    const link = drawer().locator('.campaign-bundles a').first();
    await link.waitFor();
    assert.match(await drawer().locator('.campaign-bundles li').first().innerText(), /PoC digest only · evidence digests only/);
    const [download] = await Promise.all([page.waitForEvent('download'), link.click()]);
    const saved = path.join(OUT, 'ui-nv14-bundle.json');
    await download.saveAs(saved);
    // The file as downloaded must hash to the digest the console shows for it.
    const shown = (await link.locator('code').innerText()).trim();
    const hashed = 'sha256:' + require('node:crypto').createHash('sha256').update(fs.readFileSync(saved)).digest('hex');
    assert.equal(hashed, shown);
    report.downloadHashMatchesDigest = true;
    const bundle = JSON.parse(fs.readFileSync(saved, 'utf8'));
    assert.equal(bundle.schema, 'nidavellir/disclosure-bundle/v1');
    assert.equal(bundle.disclosure.state, 'fixed');
    assert.equal(bundle.members.length, 2);
    assert.ok(bundle.members.every((member) => member.poc.included === false && !('text_redacted' in member.poc)));
    report.bundle = { members: bundle.members.length, state: bundle.disclosure.state, bytes: fs.statSync(saved).size };
    fs.unlinkSync(saved);
    await drawer().getByLabel('Include PoC text (redacted)').check();
    assert.match(await drawer().innerText(), /Redaction is pattern-based\. Read the bundle before sharing it\./);
    await drawer().getByLabel('Include PoC text (redacted)').uncheck();
    check('A default bundle was generated and downloaded: two members, digests only, no PoC text; choosing to include PoC text shows the redaction warning');
    await noHorizontalScroll('drawer');
    assert.ok(!CLAIMS.test(await drawer().innerText()));
    await closeDrawer();

    // --- an unsupported state stays visible ----------------------------------------
    if (SINGLE) {
      await addFinding(SINGLE);
      await page.waitForFunction(() => document.querySelectorAll('.campaign-findings tbody tr').length === 2);
      await openRow(1);
      await saveState('Fixed', '', '');
      await drawer().getByText('Recorded as fixed.').waitFor();
      assert.match(await drawer().innerText(), /Not supported by recorded evidence/);
      await closeDrawer();
      assert.match(await rows().nth(1).innerText(), /Not supported by recorded evidence/);
      const open = page.locator('.source-review-banner.incomplete');
      await open.waitFor();
      assert.match(await open.innerText(), /Open points in this campaign/);
      assert.match(await open.innerText(), /marked fixed, but the recorded evidence outcome is unknown/);
      assert.equal(await open.locator('button, a, summary, input').count(), 0);
      check('Marking a single-version finding fixed was accepted and shown as not supported by the evidence, in the row and in a banner that cannot be dismissed');
    }

    // --- survives reload and a new login ----------------------------------------------
    await page.reload();
    await rows().first().waitFor();
    assert.match(await rows().first().innerText(), /Fixed/);
    assert.match(await rows().first().innerText(), /1 bundle/);
    await page.goto(`${WEB}/console`);
    await page.locator('details.profile summary').click();
    await page.getByRole('button', { name: 'Log out' }).click();
    await page.goto(campaignUrl);
    await login();
    await rows().first().waitFor();
    await openRow(0);
    assert.match(await drawer().locator('.source-review-history').first().innerText(), /Reference: GHSA-demo/);
    assert.equal(await drawer().locator('.campaign-bundles li').count(), 1);
    await closeDrawer();
    check('State, history and the bundle were unchanged after a reload and after log out and log in');

    // --- write routes need session and CSRF ----------------------------------------------
    const csrf = await page.evaluate(async () => {
      const id = location.pathname.split('/').pop();
      const url = `/api/console/research/campaigns/${id}/findings/${'a'.repeat(12)}/disclosure`;
      const send = (headers) => fetch(url, { method: 'POST', credentials: 'same-origin',
        headers: { 'Content-Type': 'application/json', ...headers }, body: JSON.stringify({ state: 'reported' }) });
      const token = document.querySelector('meta[name="csrf-token"]').content;
      return { without: (await send({})).status, wrong: (await send({ 'X-CSRFToken': 'nope' })).status,
               withToken: (await send({ 'X-CSRFToken': token })).status };
    });
    assert.deepEqual(csrf, { without: 400, wrong: 400, withToken: 404 });
    check('The disclosure write route refused a missing or wrong CSRF token (400)');

    // --- keyboard ---------------------------------------------------------------------------
    const trigger = rows().first().locator('th button');
    await trigger.focus();
    const triggerText = await trigger.innerText();
    await page.keyboard.press('Enter');
    await drawer().waitFor();
    for (let index = 0; index < 30; index += 1) {
      await page.keyboard.press('Tab');
      assert.ok(await page.evaluate(() => {
        const active = document.activeElement;
        return active === document.body || Boolean(active.closest('dialog.source-review-drawer'));
      }), 'focus left the open drawer');
    }
    await page.keyboard.press('Escape');
    await drawer().waitFor({ state: 'detached' });
    assert.equal(await page.evaluate(() => document.activeElement.textContent), triggerText);
    check('Keyboard: Enter opens the drawer, Tab stays inside it, Escape closes it and focus returns to the row');

    // --- reflow and wording ---------------------------------------------------------------------
    await noHorizontalScroll('campaign');
    // The standing note denies such a claim in so many words; everything else must not make one.
    assert.ok(!CLAIMS.test((await page.locator('main').innerText()).replace(STANDING, '')));
    await page.goto(`${WEB}/console/research/campaigns`);
    await page.locator('.campaign-list li').first().waitFor();
    assert.match(await page.locator('.campaign-list').innerText(), SINGLE ? /2 finding groups/ : /1 finding group/);
    await noHorizontalScroll('list');
    check(`No sideways scroll at ${WIDTHS.join(', ')} px on the list, the form, a campaign and an open drawer; no view text claims a version is safe or unaffected`);

    assert.deepEqual(errors, []);
    report.result = 'passed';
  } catch (error) {
    report.result = 'failed';
    report.error = String(error && error.stack || error);
    report.url = page.url();
    await page.screenshot({ path: path.join(OUT, 'ui-nv14-failure.png'), fullPage: true }).catch(() => {});
    process.exitCode = 1;
  } finally {
    report.pageErrors = errors;
    fs.writeFileSync(path.join(OUT, 'ui-nv14-browser-check.json'), JSON.stringify(report, null, 2));
    console.log(JSON.stringify(report, null, 2));
    await browser.close();
  }
})();
