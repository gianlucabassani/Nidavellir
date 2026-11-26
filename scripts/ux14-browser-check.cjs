// UX-14 browser check: the operations page. Against a mock stack with one
// destroyed arena whose labelled container was left behind (a hand-made
// orphan) and, when NV_UX14_WORKER is set, the stack's worker container name
// so the check can stop it and see the heartbeat go (then start it again).
// NV_UX14_CONFIG: {"leftover"} (the destroyed arena id).
const assert = require('node:assert/strict');
const fs = require('node:fs');
const {execFileSync} = require('node:child_process');
const {chromium} = require(process.env.NV_PLAYWRIGHT_MODULE || 'playwright');
const config = JSON.parse(fs.readFileSync(process.env.NV_UX14_CONFIG, 'utf8'));
const WEB = process.env.NV_WEB || 'http://127.0.0.1:15020';
const SHOTS = process.env.NV_UX14_SHOTS || '';
const WORKER = process.env.NV_UX14_WORKER || '';

(async () => {
  const browser = await chromium.launch({headless: true,
    executablePath: process.env.NV_CHROMIUM_PATH || undefined, args: ['--no-sandbox']});
  const page = await (await browser.newContext({viewport: {width: 1440, height: 1000}})).newPage();
  const errors = []; page.on('pageerror', error => errors.push(String(error)));
  const checks = [];
  const shot = async name => SHOTS && page.screenshot({path: `${SHOTS}/${name}.png`, fullPage: true});
  const tile = label => page.locator('.op-tile').filter({has: page.locator('.label', {hasText: new RegExp(`^${label}$`, 'i')})});
  const refresh = async () => {
    await page.getByRole('button', {name: 'Refresh workspace data'}).click();
    await page.waitForResponse(r => r.url().endsWith('/api/console/operations'));
  };
  try {
    await page.goto(`${WEB}/console/operations`);
    await page.getByLabel('Username').fill(process.env.NV_USER || 'admin');
    await page.getByLabel('Password').fill(process.env.NV_PASSWORD || 'nidavellir');
    await page.getByRole('button', {name: 'Sign in'}).click();
    await page.locator('.op-tiles').waitFor();
    assert.match(await tile('Platform').innerText(), /Ready/);
    assert.match(await tile('Worker').innerText(), /Alive/);
    const deps = await page.locator('.op-deps li').allInnerTexts();
    for (const name of ['Database', 'Redis', 'Docker'])
      assert.ok(deps.some(d => d.startsWith(name) && /OK/.test(d)), `${name}: ${deps}`);
    assert.match(await page.locator('.fl-kv').innerText(), /Migration\s+\S+ \(latest\)/);
    const stores = await page.locator('.op-table').first().innerText();
    for (const name of ['Database', 'Evidence artifacts', 'HTTP transactions']) assert.ok(stores.includes(name));
    assert.equal(await page.locator('.rail-nav [aria-current="page"]').innerText(), 'Operations');
    await shot('operations');
    checks.push('tiles, dependencies, migration revision and stores render; the sidebar marks Operations');

    // The hand-made orphan of a destroyed arena is listed and reclaimable.
    const row = page.locator('.op-table tbody tr').filter({hasText: config.leftover});
    await row.waitFor();
    assert.match(await row.innerText(), /Left after teardown/i);
    // Arenas this installation does not know are never offered for reclaim.
    for (const unknown of await page.locator('tr.op-unknown').all())
      assert.equal(await unknown.getByRole('button', {name: 'Reclaim'}).count(), 0);
    await row.getByRole('button', {name: 'Reclaim'}).click();
    await row.getByRole('button', {name: 'Remove resources'}).click();
    await page.getByText(/Reclaim of .* queued/).waitFor();
    let gone = false;
    for (let i = 0; i < 15 && !gone; i++) {
      await page.waitForTimeout(2000);
      await refresh();
      gone = (await page.locator('.op-table tbody tr').filter({hasText: config.leftover}).count()) === 0;
    }
    assert.ok(gone, 'the orphan disappears once the worker reclaimed it');
    checks.push('a hand-made labelled orphan appears as left after teardown and is reclaimed; unknown arenas offer no reclaim');

    if (WORKER) {
      execFileSync('docker', ['stop', WORKER], {stdio: 'ignore'});
      try {
        let dead = false;
        for (let i = 0; i < 20 && !dead; i++) {
          await page.waitForTimeout(5000);
          await refresh();
          dead = /No heartbeat|Stale/.test(await tile('Worker').innerText());
        }
        assert.ok(dead, 'a stopped worker shows on the next refresh after its heartbeat expires');
        await shot('operations-worker-down');
      } finally {
        execFileSync('docker', ['start', WORKER], {stdio: 'ignore'});
      }
      checks.push('stopping the worker shows "No heartbeat" on the next refresh after the beat expires');
    }

    await page.setViewportSize({width: 390, height: 844});
    await page.reload();
    await page.locator('.op-tiles').waitFor();
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
