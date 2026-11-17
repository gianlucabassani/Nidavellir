// UI-R4 acceptance journey over one captured session of a pinned checkout.
//
// scripts/verify-ui-r4-live.py runs this; it can also be run alone against a
// disposable instance. NV_R4_MODE:
//   journey  page through every site of NV_R4_PATTERN, open drawers on the first,
//            a middle and the last page, mark the first three sites, then reload
//            and log out and in;
//   verify   only check that those three states, notes and history are still shown
//            (after a service restart or a restore).
//
//   NV_PLAYWRIGHT_MODULE=/path/to/node_modules/playwright NV_CHROMIUM_PATH=/path/to/chromium \
//   NV_R4_WEB=http://127.0.0.1:15014 NV_R4_PASSWORD=... NV_R4_SESSION=<32 hex> \
//   NV_R4_PATTERN=unscoped-queryset NV_R4_TOTAL=2846 NV_R4_SHA=<40 hex> NV_R4_REF=v3.3.0 \
//   NV_R4_MODE=journey NV_R4_OUT=/path/to/report.json node scripts/ui-r4-pinned-browser-check.cjs
const assert = require('node:assert/strict');
const fs = require('node:fs');
const { chromium } = require(process.env.NV_PLAYWRIGHT_MODULE || 'playwright');

const WEB = process.env.NV_R4_WEB || 'http://127.0.0.1:15014';
const USER = process.env.NV_R4_USER || 'admin';
const PASSWORD = process.env.NV_R4_PASSWORD || '';
const SESSION = process.env.NV_R4_SESSION || '';
const PATTERN = process.env.NV_R4_PATTERN || 'unscoped-queryset';
const TOTAL = Number(process.env.NV_R4_TOTAL || 0);
const MODE = process.env.NV_R4_MODE || 'journey';
const OUT = process.env.NV_R4_OUT || 'ui-r4-pinned-browser-check.json';
const CAPTION = 'Statuses and classifications are syntactic candidates, not findings.';
const NOTES = {
  Dismissed: 'Acceptance run: dismissed with a note of sufficient length.',
  'In review': 'Acceptance run: in review.',
  Candidate: 'Acceptance run: candidate, no finding linked.',
};
const EXPECTED = ['Dismissed', 'In review', 'Candidate', 'Unreviewed'];

(async () => {
  assert.match(SESSION, /^[0-9a-f]{32}$/);
  const browser = await chromium.launch({
    headless: true,
    executablePath: process.env.NV_CHROMIUM_PATH || undefined,
    args: ['--no-sandbox'],
  });
  const page = await (await browser.newContext({ viewport: { width: 1440, height: 900 } })).newPage();
  const errors = [];
  page.on('pageerror', (error) => errors.push(String(error)));
  const report = { date: new Date().toISOString(), mode: MODE, session: SESSION, pattern: PATTERN, checks: [] };
  const check = (text) => report.checks.push(text);
  const url = `${WEB}/console/research/review/${SESSION}`;
  const rows = () => page.locator('.source-review-sites tbody tr');
  const paging = () => page.locator('.source-review-paging');
  const states = async () =>
    (await rows().locator('td:last-child .source-review-state').allInnerTexts()).slice(0, 4);
  const onPage = (number) => page.waitForFunction((value) =>
    document.querySelector('.source-review-paging [role=status]')?.textContent.includes(`page ${value} of`), number);

  async function login() {
    await page.getByLabel('Username').fill(USER);
    await page.getByLabel('Password').fill(PASSWORD);
    await page.getByRole('button', { name: 'Sign in' }).click();
  }
  async function openPattern() {
    await page.locator('.source-review-patterns').getByRole('button', { name: PATTERN, exact: true }).click();
    await page.getByRole('heading', { name: `Sites · ${PATTERN}` }).waitFor();
    await rows().first().waitFor();
  }
  async function openSite(index) {
    await rows().nth(index).locator('th button').click();
    const drawer = page.locator('dialog.source-review-drawer');
    await drawer.waitFor();
    const text = await drawer.innerText();
    assert.match(text, /Machine status/i);
    assert.match(text, /Classification reason/i);
    assert.match(text, /Operator review state/i);
    assert.ok(text.includes(CAPTION));
    return drawer;
  }
  async function closeDrawer(drawer) {
    await drawer.getByRole('button', { name: 'Close', exact: true }).click();
    await drawer.waitFor({ state: 'detached' });
  }
  async function historyShown() {
    for (const [index, label] of EXPECTED.slice(0, 3).entries()) {
      const drawer = await openSite(index);
      assert.ok((await drawer.locator('.source-review-history').innerText()).includes(NOTES[label]));
      await closeDrawer(drawer);
    }
  }

  try {
    await page.goto(url);
    await login();
    await page.locator('.source-review-banner').waitFor();
    const identity = await page.locator('.source-review-identity').innerText();
    if (process.env.NV_R4_SHA) assert.ok(identity.includes(process.env.NV_R4_SHA));
    if (process.env.NV_R4_REF) assert.ok(identity.includes(`requested as ${process.env.NV_R4_REF}`));
    assert.match(identity, /sha256:[0-9a-f]{64}/);
    report.snapshot_digest = identity.match(/sha256:[0-9a-f]{64}/)[0];
    await openPattern();
    assert.equal(await page.locator('.source-review-sites caption').innerText(), CAPTION);

    if (MODE === 'verify') {
      assert.deepEqual(await states(), EXPECTED);
      await historyShown();
      check('The three review states, their notes and history are shown unchanged');
    } else {
      assert.ok(!(await page.locator('.source-review-banner').getAttribute('class')).includes('incomplete'));
      const status = await paging().locator('[role=status]').innerText();
      const pages = Number(status.match(/page \d+ of (\d+)/)[1]);
      assert.equal(Number(status.match(/of (\d+)/)[1]), TOTAL);
      const seen = [];
      for (let index = 1; index <= pages; index += 1) {
        await onPage(index);
        await rows().first().waitFor();
        seen.push(...await rows().locator('th button').allInnerTexts());
        // Every row carries machine status, classification and an operator state.
        const cells = await rows().first().locator('td').allInnerTexts();
        assert.ok(cells[0].trim().length > 0 && cells[cells.length - 1].trim().length > 0);
        if (index < pages) await paging().getByRole('button', { name: 'Next →' }).click();
      }
      assert.equal(seen.length, TOTAL);
      assert.equal(new Set(seen).size, TOTAL);
      assert.ok(await paging().getByRole('button', { name: 'Next →' }).isDisabled());
      report.pages = pages;
      report.sites = seen.length;
      check(`Paging from the first page to the last showed ${seen.length} ${PATTERN} sites on ${pages} pages with no duplicate`);

      const middle = Math.ceil(pages / 2);
      report.drawers = [];
      for (const [number, go] of [
        [middle, async () => {
          await paging().getByLabel('Go to page').fill(String(middle));
          await paging().getByRole('button', { name: 'Go', exact: true }).click();
        }],
        [pages, () => paging().getByRole('button', { name: 'Last', exact: true }).click()],
        [1, () => paging().getByRole('button', { name: 'First', exact: true }).click()],
      ]) {
        await go();
        await onPage(number);
        await rows().first().waitFor();
        report.drawers.push({ page: number, site: await rows().first().locator('th button').innerText() });
        await closeDrawer(await openSite(0));
      }
      check(`A site drawer opened on page 1, page ${middle} and page ${pages}`);

      for (const [index, label] of EXPECTED.slice(0, 3).entries()) {
        const machine = await rows().nth(index).locator('td').first().innerText();
        const drawer = await openSite(index);
        await drawer.getByLabel(label, { exact: true }).check();
        if (label === 'Dismissed') {
          await drawer.getByRole('button', { name: 'Save review state' }).click();
          assert.match(await drawer.getByRole('alert').innerText(), /at least 10 characters/);
        }
        await drawer.getByLabel('Note', { exact: false }).fill(NOTES[label]);
        await drawer.getByRole('button', { name: 'Save review state' }).click();
        await drawer.getByText(`Recorded as ${label.toLowerCase()}.`).waitFor();
        await closeDrawer(drawer);
        await page.waitForFunction(([row, text]) =>
          document.querySelectorAll('.source-review-sites tbody tr')[row]
            ?.querySelector('td:last-child')?.textContent.includes(text), [index, label]);
        assert.equal(await rows().nth(index).locator('td').first().innerText(), machine);
      }
      assert.deepEqual(await states(), EXPECTED);
      check('One site each was marked dismissed, in review and candidate with a note; machine status and reason stayed beside each');

      await page.reload();
      await rows().first().waitFor();
      assert.deepEqual(await states(), EXPECTED);
      await page.goto(`${WEB}/console`);
      await page.locator('details.profile summary').click();
      await page.getByRole('button', { name: 'Log out' }).click();
      await page.goto(url);
      await login();
      await page.locator('.source-review-banner').waitFor();
      await openPattern();
      assert.deepEqual(await states(), EXPECTED);
      await historyShown();
      check('States, notes and history were unchanged after a reload and after log out and log in');
    }
    assert.deepEqual(errors, []);
    report.result = 'passed';
  } catch (error) {
    report.result = 'failed';
    report.error = String(error && error.stack || error);
    report.url = page.url();
    await page.screenshot({ path: `${OUT}.failure.png`, fullPage: true }).catch(() => {});
    process.exitCode = 1;
  } finally {
    report.pageErrors = errors;
    fs.writeFileSync(OUT, JSON.stringify(report, null, 2));
    console.log(JSON.stringify(report, null, 2));
    await browser.close();
  }
})();
