// Real-service browser review, run before and after arena teardown.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const { chromium } = require(process.env.NV_PLAYWRIGHT_MODULE || 'playwright');
const config = JSON.parse(fs.readFileSync(process.env.NV_R2_CONFIG, 'utf8'));
const WEB = 'http://127.0.0.1:15006';
(async () => {
  const browser = await chromium.launch({headless: true,
    executablePath: process.env.NV_CHROMIUM_PATH || undefined, args: ['--no-sandbox']});
  const context = await browser.newContext();
  const page = await context.newPage();
  const errors = [];
  page.on('pageerror', error => errors.push(String(error)));
  const report = {date: new Date().toISOString(), cases: [], page_errors: errors};
  try {
    await page.goto(WEB + '/login');
    await page.getByLabel('Username').fill('admin');
    await page.getByLabel('Password').fill('nv06-local-only');
    await page.getByRole('button', {name: 'Sign in'}).click();
    for (const item of config.cases) {
      await page.goto(WEB + `/console/arena/${item.arena}?tab=findings`);
      const card = page.locator('.finding-card').filter({hasText: 'A reads B private object'}).last();
      await card.locator('summary').filter({hasText: 'Review controls and evidence'}).click();
      const review = card.locator('.control-evidence-review');
      await review.getByRole('heading', {name: 'Prerequisite controls'}).waitFor();
      await review.getByRole('heading', {name: 'Observed effects'}).waitFor();
      assert.ok((await review.innerText()).toLowerCase().includes(item.review.verdict.replaceAll('_', ' ')) ||
        (await review.innerText()).toLowerCase().includes(item.review.verdict), `${item.name}: ${await review.innerText()}`);
      const refute = card.getByRole('button', {name: 'Refute', exact: true});
      if (await refute.count()) assert.equal(await refute.isEnabled(), item.review.refutation_allowed);
      if (item.name === 'failed-control') {
        assert.match(await review.innerText(), /failed/);
        assert.match(await review.innerText(), /Unresolved evidence/);
      }
      const response = await page.request.get(WEB + `/api/console/arenas/${item.arena}/findings/${item.finding_id}/review`);
      assert.equal(response.status(), 200);
      assert.equal((await response.json()).verdict, item.review.verdict);
      assert.ok(!(await review.innerText()).includes('token-b-operator'));
      if (item.name === 'disclosure') {
        const csrf = await page.locator('meta[name="csrf-token"]').getAttribute('content');
        const saved = await page.request.post(WEB + `/api/arenas/${item.arena}/findings/${item.finding_id}/verify`, {
          headers: {'X-CSRFToken': csrf}, data: {verdict: 'refuted', note: 'UI-R2 operator-judgment retention check'},
        });
        assert.equal(saved.status(), 200);
        await page.getByRole('button', {name: 'Refresh ↻', exact: true}).click();
        await page.waitForFunction(() => document.querySelector('.finding-card > .finding-title')?.textContent.toLowerCase().includes('refuted'));
        assert.match(await review.innerText(), /confirmed/i);
        await page.reload();
        await card.locator('summary').filter({hasText: 'Review controls and evidence'}).click();
        await review.getByRole('heading', {name: 'Prerequisite controls'}).waitFor();
        assert.match(await card.locator(':scope > .finding-title').innerText(), /refuted/i);
        assert.match(await review.innerText(), /confirmed/i);
      }
      const links = await review.locator('a').evaluateAll(anchors => anchors.map(a => a.href));
      for (const link of links) assert.equal((await page.request.get(link)).status(), 200);
      for (const width of [320, 390, 1440]) {
        await page.setViewportSize({width, height: 1000});
        assert.ok(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 1), `Overflow at ${width}`);
      }
      await page.screenshot({path: config.output + '.' + item.name + '.png', fullPage: true});
      report.cases.push({name: item.name, verdict: item.review.verdict, links_checked: links.length,
        widths: [320,390,1440], control_states: item.review.controls.map(c => c.state)});
      if (item.missing_action) {
        const unresolved = page.locator('.finding-card').filter({hasText: 'A reads B private object'}).first();
        await unresolved.locator('summary').filter({hasText: 'Review controls and evidence'}).click();
        await unresolved.getByText('Unresolved evidence', {exact: true}).waitFor();
      }
    }
    assert.deepEqual(errors, []);
    fs.writeFileSync(config.output, JSON.stringify(report, null, 2), {flag: 'wx'});
  } catch (error) { await page.screenshot({path: config.output + '.failure.png', fullPage: true}); throw error; } finally {await browser.close();}
})().catch(error => {console.error(error); process.exit(1);});
