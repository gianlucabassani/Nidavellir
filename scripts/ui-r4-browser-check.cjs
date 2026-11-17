// UI-R4 console journey against a running console + service.
//
// The research checkout behind the service must contain:
//   - at least three pages (over 100 sites) of `unscoped-queryset` matches under src/documents/,
//   - a `privilege-flags` inventory that exceeds the grep cap (a lower-bound count),
//   - refs `affected-1` and `fixed-1` whose diff exceeds the git output cap.
// It creates sessions and review states; run it only against a disposable instance.
//
//   NV_PLAYWRIGHT_MODULE=/path/to/node_modules/playwright NV_CHROMIUM_PATH=/path/to/chromium \
//   NV_R4_WEB=http://127.0.0.1:15081 NV_R4_PASSWORD=... NV_R4_OUT=/path/to/output-dir \
//   node scripts/ui-r4-browser-check.cjs
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const { chromium } = require(process.env.NV_PLAYWRIGHT_MODULE || 'playwright');

const WEB = process.env.NV_R4_WEB || 'http://127.0.0.1:15081';
const USER = process.env.NV_R4_USER || 'admin';
const PASSWORD = process.env.NV_R4_PASSWORD || '';
const OUT = process.env.NV_R4_OUT || '.';
const CAPTION = 'Statuses and classifications are syntactic candidates, not findings.';
const WIDTHS = [320, 390, 1440];

(async () => {
  const browser = await chromium.launch({
    headless: true,
    executablePath: process.env.NV_CHROMIUM_PATH || undefined,
    args: ['--no-sandbox'],
  });
  const context = await browser.newContext({ viewport: { width: 1440, height: 900 } });
  const page = await context.newPage();
  const errors = [];
  page.on('pageerror', (error) => errors.push(String(error)));
  const reviewPosts = [];
  page.on('request', (request) => {
    if (request.method() === 'POST' && request.url().endsWith('/review')) reviewPosts.push(request.url());
  });
  const report = { date: new Date().toISOString(), web: WEB, checks: [], reflow: [] };
  const check = (text) => report.checks.push(text);

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
      await page.screenshot({ path: path.join(OUT, `ui-r4-${label}-${width}.png`), fullPage: false });
    }
    await page.setViewportSize({ width: 1440, height: 900 });
  }
  async function createSession({ name, keep, scope, link }) {
    await page.goto(`${WEB}/console/research/review`);
    await page.getByRole('button', { name: 'New session', exact: true }).click();
    await page.getByLabel('Session name').fill(name);
    await page.getByLabel('Commit, tag or branch').fill('HEAD');
    for (const box of await page.locator('.source-review-checks input[type=checkbox]').all()) {
      const label = (await box.locator('xpath=..').innerText()).trim();
      await box.setChecked(keep.includes(label));
    }
    if (scope) await page.getByLabel('Path scope', { exact: false }).fill(scope);
    if (link) {
      await page.getByRole('button', { name: 'Add a fix link' }).click();
      await page.getByLabel('Label', { exact: true }).fill(link.label);
      await page.getByLabel('Fix commit').fill(link.fix);
      await page.getByLabel('Affected ref').fill(link.affected);
      await page.getByLabel('Fixed ref').fill(link.fixed);
    }
    await page.getByRole('button', { name: 'Create session and capture' }).click();
    await page.waitForURL(/\/console\/research\/review\/[0-9a-f]{32}$/);
    // The page polls while the worker captures; wait for a terminal state.
    await page.locator('.source-review-banner').waitFor();
    await page.waitForFunction(
      () => !document.querySelector('.source-review-banner')?.textContent.includes('Capture in progress'),
      null, { timeout: 600000 });
    return page.url();
  }
  const rows = () => page.locator('.source-review-sites tbody tr');
  const sitePaging = () => page.locator('.source-review-paging');
  async function selectPattern(name) {
    await page.locator('.source-review-patterns').getByRole('button', { name, exact: true }).click();
    await page.getByRole('heading', { name: `Sites · ${name}` }).waitFor();
    await rows().first().waitFor();
  }
  async function pageNumber() {
    const text = await sitePaging().locator('[role=status]').innerText();
    return text.match(/page (\d+) of (\d+)/).slice(1).map(Number);
  }
  async function openFirstSite() {
    await rows().first().locator('th button').click();
    const drawer = page.locator('dialog.source-review-drawer');
    await drawer.waitFor();
    assert.match(await drawer.innerText(), /Machine status/i);
    assert.match(await drawer.innerText(), /Classification reason/i);
    assert.match(await drawer.innerText(), /Operator review state/i);
    assert.ok((await drawer.innerText()).includes(CAPTION));
    return drawer;
  }
  async function closeDrawer(drawer) {
    await drawer.getByRole('button', { name: 'Close', exact: true }).click();
    await drawer.waitFor({ state: 'detached' });
  }

  try {
    fs.mkdirSync(OUT, { recursive: true });
    await page.goto(`${WEB}/console/research/review`);
    await login();
    await page.getByRole('heading', { name: 'Source review', exact: true }).waitFor();
    check('Unauthenticated visit was sent to login; the session list loaded after sign-in');

    // --- a complete session ---------------------------------------------------
    const completeUrl = await createSession({
      name: 'Browser check: complete', keep: ['unscoped-queryset'], scope: 'src/documents/' });
    let banner = page.locator('.source-review-banner');
    assert.ok(!(await banner.getAttribute('class')).includes('incomplete'));
    assert.match(await banner.innerText(), /syntactic candidates, not findings/);
    assert.equal(await page.locator('.source-review-patterns tbody tr').count(), 1);
    assert.match(await page.locator('.source-review-patterns tbody tr').innerText(), /exact/);
    check('Complete session: full commit SHA, snapshot digest and the standing limits note are shown');
    const sha = await page.locator('.source-review-identity code').nth(1).innerText();
    assert.match(sha, /^[0-9a-f]{40}$/);
    assert.match(await page.locator('.source-review-identity').innerText(), /requested as HEAD/);
    assert.match(await page.locator('.source-review-identity').innerText(), /sha256:[0-9a-f]{64}/);

    // Every retained site is reachable by paging, with no duplicate.
    await rows().first().waitFor();
    assert.equal(await page.locator('.source-review-sites caption').innerText(), CAPTION);
    const [, pages] = await pageNumber();
    assert.ok(pages >= 3, `need at least three site pages, got ${pages}`);
    const total = Number((await sitePaging().locator('[role=status]').innerText()).match(/of (\d+)/)[1]);
    const seen = [];
    for (let index = 1; index <= pages; index += 1) {
      await page.waitForFunction((expected) =>
        document.querySelector('.source-review-paging [role=status]')?.textContent.includes(`page ${expected} of`), index);
      await rows().first().waitFor();
      seen.push(...await rows().locator('th button').allInnerTexts());
      if (index < pages) await sitePaging().getByRole('button', { name: 'Next →' }).click();
    }
    assert.equal(seen.length, total);
    assert.equal(new Set(seen).size, total);
    assert.ok(await sitePaging().getByRole('button', { name: 'Next →' }).isDisabled());
    check(`Paging from the first page to the last returned ${total} sites on ${pages} pages with no duplicate`);

    // First, a middle and the last page each open a drawer.
    const middle = Math.ceil(pages / 2);
    for (const [label, go] of [
      ['first', () => sitePaging().getByRole('button', { name: 'First', exact: true }).click()],
      ['middle', async () => {
        await sitePaging().getByLabel('Go to page').fill(String(middle));
        await sitePaging().getByRole('button', { name: 'Go', exact: true }).click();
      }],
      ['last', () => sitePaging().getByRole('button', { name: 'Last', exact: true }).click()],
    ]) {
      await go();
      const expected = label === 'first' ? 1 : label === 'middle' ? middle : pages;
      await page.waitForFunction((value) =>
        document.querySelector('.source-review-paging [role=status]')?.textContent.includes(`page ${value} of`), expected);
      await rows().first().waitFor();
      await closeDrawer(await openFirstSite());
    }
    check(`Site drawers opened on page 1, page ${middle} and page ${pages}`);
    assert.match(page.url(), /offset=\d+/);

    // A cut evidence line is flagged.
    await page.getByLabel('File path starts with').fill('src/documents/wide');
    await page.getByRole('button', { name: 'Apply path' }).click();
    await page.waitForFunction(() => document.querySelectorAll('.source-review-sites tbody tr').length === 1);
    assert.match(await rows().first().innerText(), /line cut/);
    check('A site whose evidence line was cut says so');
    await page.getByLabel('File path starts with').fill('');
    await page.getByRole('button', { name: 'Apply path' }).click();
    await page.waitForFunction(() => document.querySelectorAll('.source-review-sites tbody tr').length === 50);

    // --- review states ---------------------------------------------------------
    // Clearing the path filter returned to the first page.
    assert.equal((await pageNumber())[0], 1);
    const machineBefore = await rows().nth(0).locator('td').first().innerText();
    let drawer = await openFirstSite();
    const postsBefore = reviewPosts.length;
    await drawer.getByLabel('Dismissed', { exact: true }).check();
    await drawer.getByRole('button', { name: 'Save review state' }).click();
    assert.match(await drawer.getByRole('alert').innerText(), /at least 10 characters/);
    assert.equal(reviewPosts.length, postsBefore);
    check('Dismissing without a note is refused in the form and nothing is sent');
    await drawer.getByLabel('Note', { exact: false }).fill('Primary-key lookup only; not worth probing.');
    await drawer.getByRole('button', { name: 'Save review state' }).click();
    await drawer.getByText('Recorded as dismissed.').waitFor();
    assert.match(await drawer.locator('.source-review-history').innerText(), /Primary-key lookup only/);
    await closeDrawer(drawer);
    await page.waitForFunction(() =>
      document.querySelector('.source-review-sites tbody tr td:last-child')?.textContent.includes('Dismissed'));
    assert.equal(await rows().nth(0).locator('td').first().innerText(), machineBefore);
    for (const [index, label] of [[1, 'In review'], [2, 'Candidate']]) {
      await rows().nth(index).locator('th button').click();
      drawer = page.locator('dialog.source-review-drawer');
      await drawer.waitFor();
      await drawer.getByLabel(label, { exact: true }).check();
      await drawer.getByLabel('Note', { exact: false }).fill(`${label} from the browser check`);
      await drawer.getByRole('button', { name: 'Save review state' }).click();
      await drawer.getByText(`Recorded as ${label.toLowerCase()}.`).waitFor();
      await closeDrawer(drawer);
    }
    const states = async () => (await rows().locator('td:last-child .source-review-state').allInnerTexts()).slice(0, 4);
    await page.waitForFunction(() =>
      document.querySelectorAll('.source-review-sites tbody tr')[2]?.textContent.includes('Candidate'));
    assert.deepEqual(await states(), ['Dismissed', 'In review', 'Candidate', 'Unreviewed']);
    assert.match(await page.locator('.source-review-patterns tbody tr').innerText(), new RegExp(`${total - 3}`));
    check('One site each was marked dismissed, in review and candidate; machine status and reason stayed beside each');

    await page.reload();
    await rows().first().waitFor();
    assert.deepEqual(await states(), ['Dismissed', 'In review', 'Candidate', 'Unreviewed']);
    await page.goto(`${WEB}/console`);
    await page.locator('details.profile summary').click();
    await page.getByRole('button', { name: 'Log out' }).click();
    await page.goto(completeUrl);
    await login();
    await rows().first().waitFor();
    assert.deepEqual(await states(), ['Dismissed', 'In review', 'Candidate', 'Unreviewed']);
    drawer = await openFirstSite();
    assert.match(await drawer.locator('.source-review-history').innerText(), /Primary-key lookup only/);
    await closeDrawer(drawer);
    check('Review states, notes and history were unchanged after a reload and after log out and log in');

    // --- write route needs session and CSRF --------------------------------------
    const csrf = await page.evaluate(async () => {
      const site = location.pathname.split('/').pop();
      const url = `/api/console/research/review-sessions/${site}/sites/${'a'.repeat(64)}/review`;
      const send = (headers) => fetch(url, { method: 'POST', credentials: 'same-origin',
        headers: { 'Content-Type': 'application/json', ...headers }, body: JSON.stringify({ state: 'in_review' }) });
      const token = document.querySelector('meta[name="csrf-token"]').content;
      return { without: (await send({})).status, wrong: (await send({ 'X-CSRFToken': 'nope' })).status,
               withToken: (await send({ 'X-CSRFToken': token })).status };
    });
    assert.deepEqual(csrf, { without: 400, wrong: 400, withToken: 404 });
    const anonymous = await browser.newContext();
    const refused = await anonymous.request.post(
      `${WEB}/api/console/research/review-sessions/${completeUrl.split('/').pop()}/sites/${'a'.repeat(64)}/review`,
      { data: { state: 'in_review' }, maxRedirects: 0 });
    assert.ok([302, 400].includes(refused.status()));
    await anonymous.close();
    check('The review write route refused a missing or wrong CSRF token (400) and a request with no session');

    // --- keyboard ----------------------------------------------------------------
    const trigger = rows().nth(3).locator('th button');
    await trigger.focus();
    const triggerText = await trigger.innerText();
    await page.keyboard.press('Enter');
    drawer = page.locator('dialog.source-review-drawer');
    await drawer.waitFor();
    for (let index = 0; index < 30; index += 1) {
      await page.keyboard.press('Tab');
      assert.ok(await page.evaluate(() => {
        const active = document.activeElement;
        return active === document.body || Boolean(active.closest('dialog.source-review-drawer'));
      }), 'focus left the open drawer');
    }
    await page.keyboard.press('Escape');
    await drawer.waitFor({ state: 'detached' });
    assert.equal(await page.evaluate(() => document.activeElement.textContent), triggerText);
    await page.locator('.source-review-patterns tbody th button').focus();
    await page.keyboard.press('Enter');
    check('Keyboard: Enter opens a drawer, Tab stays inside it, Escape closes it and focus returns to the site');

    // --- reflow ------------------------------------------------------------------
    await noHorizontalScroll('session');
    await rows().first().locator('th button').click();
    await page.locator('dialog.source-review-drawer').waitFor();
    await noHorizontalScroll('drawer');
    await closeDrawer(page.locator('dialog.source-review-drawer'));

    // --- an incomplete session ---------------------------------------------------
    await createSession({
      name: 'Browser check: incomplete', keep: ['unscoped-queryset', 'privilege-flags'],
      link: { label: 'GHSA demo', fix: 'fixed-1', affected: 'affected-1', fixed: 'fixed-1' } });
    banner = page.locator('.source-review-banner.incomplete');
    await banner.waitFor();
    assert.match(await banner.innerText(), /This inventory is incomplete/);
    assert.match(await banner.innerText(), /lower bound/);
    assert.match(await banner.innerText(), /Fix link F1/);
    assert.equal(await banner.locator('button, a, summary, input').count(), 0);
    await page.keyboard.press('Escape');
    await page.reload();
    await page.locator('.source-review-banner.incomplete').waitFor();
    const flags = page.locator('.source-review-patterns tbody tr').filter({ hasText: 'privilege-flags' });
    assert.match(await flags.innerText(), /lower bound/);
    assert.match(await page.locator('.source-review-patterns tbody tr').filter({ hasText: 'unscoped-queryset' }).innerText(), /exact/);
    check('Incomplete session: the banner lists every reason, has no control to dismiss it and survives a reload; the pattern row says "lower bound"');

    await selectPattern('privilege-flags');
    assert.match(await rows().first().innerText(), /manual-review/);
    assert.match(await rows().first().innerText(), /unparsed-source/);
    check('Sites in a file over the size cap are listed as manual-review / unparsed-source');
    await sitePaging().getByRole('button', { name: 'Last', exact: true }).click();
    await page.waitForFunction(() => /page (\d+) of \1/.test(
      document.querySelector('.source-review-paging [role=status]')?.textContent || ''));
    await rows().first().waitFor();
    await closeDrawer(await openFirstSite());
    report.lowerBoundPages = (await pageNumber())[1];
    check(`The last of ${report.lowerBoundPages} pages of the lower-bound pattern opened, with a drawer`);

    await selectPattern('unscoped-queryset');
    await page.getByLabel('File path starts with').fill('src/documents/views');
    await page.getByRole('button', { name: 'Apply path' }).click();
    await page.waitForFunction(() => document.querySelectorAll('.source-review-sites tbody tr').length === 1);
    assert.match(await rows().first().innerText(), /Same file as fix F1/);
    drawer = await openFirstSite();
    await drawer.getByRole('button', { name: 'Same file as fix F1 (GHSA demo)' }).click();
    const detail = page.locator('.source-review-fix-detail');
    await detail.waitFor();
    assert.match(await detail.innerText(), /Counts incomplete/i);
    assert.match(await detail.innerText(), /at least \d+/);
    assert.match(await detail.innerText(), /Output was cut/);
    assert.ok(!/same flaw\b/i.test((await detail.innerText()).replace('not thereby the same flaw', '')));
    check('Fix link panel: a cut diff shows "Counts incomplete" and "Output was cut"; the site row reads "Same file as fix F1"');
    await noHorizontalScroll('incomplete');

    await page.goto(`${WEB}/console/research/review`);
    await page.locator('.source-review-sessions li').first().waitFor();
    const list = await page.locator('.source-review-sessions').innerText();
    assert.match(list, /Incomplete/);
    assert.match(list, /Complete/);
    assert.match(list, /3 of \d+ sites reviewed/);
    await noHorizontalScroll('list');
    await page.getByRole('button', { name: 'New session', exact: true }).click();
    await noHorizontalScroll('new-session');
    check('Session list shows the complete / incomplete badge and review progress');
    check(`No sideways scroll at ${WIDTHS.join(', ')} px on the list, the form, a session, the incomplete session and an open drawer`);

    assert.deepEqual(errors, []);
    report.result = 'passed';
  } catch (error) {
    report.result = 'failed';
    report.error = String(error && error.stack || error);
    report.url = page.url();
    await page.screenshot({ path: path.join(OUT, 'ui-r4-failure.png'), fullPage: true }).catch(() => {});
    process.exitCode = 1;
  } finally {
    report.pageErrors = errors;
    fs.writeFileSync(path.join(OUT, 'ui-r4-browser-check.json'), JSON.stringify(report, null, 2));
    console.log(JSON.stringify(report, null, 2));
    await browser.close();
  }
})();
