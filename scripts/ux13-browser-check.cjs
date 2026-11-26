// UX-13 browser check: command palette, operator shell, node log tail, HTTP
// ledger rows/panes/side-by-side diff and global search by digest prefix,
// against a mock stack with one seeded active arena.
// NV_UX13_CONFIG: {"arena","a","b"} (arena id, two transaction digests; b is a
// replay of a with a different body).
const assert = require('node:assert/strict');
const fs = require('node:fs');
const {chromium} = require(process.env.NV_PLAYWRIGHT_MODULE || 'playwright');
const config = JSON.parse(fs.readFileSync(process.env.NV_UX13_CONFIG, 'utf8'));
const WEB = process.env.NV_WEB || 'http://127.0.0.1:15020';
const API = process.env.NV_API || 'http://127.0.0.1:18020';
const KEY = process.env.NV_API_KEY || 'dev-insecure-key';
const SHOTS = process.env.NV_UX13_SHOTS || '';
(async () => {
  const browser = await chromium.launch({headless: true,
    executablePath: process.env.NV_CHROMIUM_PATH || undefined, args: ['--no-sandbox']});
  const page = await (await browser.newContext({viewport: {width: 1440, height: 1000}})).newPage();
  const errors = []; page.on('pageerror', error => errors.push(String(error)));
  const checks = [];
  const shot = async name => SHOTS && page.screenshot({path: `${SHOTS}/${name}.png`, fullPage: true});
  const arena = `${WEB}/console/arena/${config.arena}`;
  const palette = page.getByRole('dialog', {name: 'Command palette'});
  try {
    await page.goto(`${arena}?tab=forge`);
    await page.getByLabel('Username').fill(process.env.NV_USER || 'admin');
    await page.getByLabel('Password').fill(process.env.NV_PASSWORD || 'nidavellir');
    await page.getByRole('button', {name: 'Sign in'}).click();
    await page.locator('.arena-layout').waitFor();

    // Palette: keyboard only, the view's own action, 0 clicks.
    let t0 = Date.now();
    await page.keyboard.press('Control+k');
    await palette.waitFor();
    await page.keyboard.type('shell');
    await palette.getByRole('option', {name: /Open Shell & logs/}).waitFor();
    await page.keyboard.press('Enter');
    await page.getByRole('heading', {name: 'Operator shell'}).waitFor();
    assert.equal(await palette.isVisible(), false);
    checks.push(`Ctrl+K → "shell" → Enter opened the shell tab with 0 clicks in ${Date.now() - t0} ms`);

    // Shell. Mock providers honestly report exec as unsupported (only
    // docker-local is live-verified), so the control is disabled with that
    // reason. The check then overrides ONLY that capability flag in the browser;
    // the command still goes through the BFF, the exec action and the mock
    // provider, and records a real span.
    assert.match(await page.locator('#shell-why').innerText(), /provider_not_implemented/);
    assert.equal(await page.getByLabel('Command', {exact: true}).isDisabled(), true);
    checks.push('Mock arena: shell disabled with the capability reason (provider_not_implemented)');
    let override = true;
    await page.route(`**/api/console/arenas/${config.arena}`, async route => {
      if (!override) return route.fallback();
      const response = await route.fetch(); const body = await response.json();
      body.capabilities = {...(body.capabilities || {}), exec: {state: 'ready', reason: ''}};
      await route.fulfill({response, json: body});
    });
    await page.reload();
    await page.getByRole('heading', {name: 'Operator shell'}).waitFor();
    const before = await (await fetch(`${API}/arenas/${config.arena}/spans?limit=500`,
      {headers: {'X-API-Key': KEY}})).json();
    await page.getByLabel('Command', {exact: true}).fill('id');
    await page.keyboard.press('Enter');
    const transcript = page.getByLabel('Shell transcript');
    await transcript.getByText(/exit 0 · \d+ ms/).waitFor();
    assert.match(await transcript.innerText(), /\$ id[\s\S]*\[mock/);
    await page.getByLabel('Command', {exact: true}).press('ArrowUp');
    assert.equal(await page.getByLabel('Command', {exact: true}).inputValue(), 'id');
    const after = await (await fetch(`${API}/arenas/${config.arena}/spans?limit=500`,
      {headers: {'X-API-Key': KEY}})).json();
    const count = body => (body.spans || []).filter(s => s.name === 'exec').length;
    assert.equal(count(after), count(before) + 1);
    checks.push('[capability flag overridden] Shell command ran through BFF → exec action → mock provider: exit code shown, history recalls it, one exec span added');
    override = false;

    // Logs: bounded tail of the selected node.
    await page.getByLabel(/^Log of /).getByText('heartbeat (simulated').first().waitFor();
    checks.push('Node log tail shows the node output');
    await shot('ux13-shell-logs');

    // HTTP: ledger rows, panes, side-by-side diff.
    await page.goto(`${arena}?tab=http`);
    const ledger = page.locator('.http-transaction');
    await ledger.first().waitFor();
    const rows = await ledger.allInnerTexts();
    assert.ok(rows.some(text => /GET \/admin\/users\s*403/.test(text)), rows.join('\n'));
    assert.ok(!rows.some(text => /Recorded transaction/.test(text)));
    const row = digest => ledger.filter({has: page.getByText(digest, {exact: true})});
    t0 = Date.now(); let clicks = 0;
    await row(config.a).getByRole('button', {name: 'Set A'}).click(); clicks++;
    await row(config.b).getByRole('button', {name: 'Set B'}).click(); clicks++;
    assert.equal(await page.getByRole('tab', {name: /Compare/}).getAttribute('aria-selected'), 'true');
    const diff = page.getByRole('table', {name: 'Response body diff, side by side'});
    await diff.waitFor();
    assert.ok(await diff.locator('.http-diff-changed').count() >= 1);
    assert.match(await diff.locator('.http-diff-changed .http-diff-a').first().innerText(), /Forbidden|guest/);
    assert.match(await diff.locator('.http-diff-changed .http-diff-b').first().innerText(), /Users|owner/);
    checks.push(`Ledger rows show method/path/status; A/B in ${clicks} clicks (${Date.now() - t0} ms) opened the Compare pane with a side-by-side coloured diff`);
    await shot('ux13-http');
    await page.reload();
    assert.equal(await page.getByRole('tab', {name: /Compare/}).getAttribute('aria-selected'), 'true');
    await page.getByRole('table', {name: 'Response body diff, side by side'}).waitFor();
    checks.push('Reload restores the Compare pane and the A/B pair (?pane=&a=&b=)');

    // Search by digest prefix from the palette → transaction detail.
    t0 = Date.now();
    await page.keyboard.press('Control+k');
    await palette.waitFor();
    await page.keyboard.type(config.a.slice(7, 19));
    const hit = palette.getByRole('option', {name: /GET \/admin\/users/}).first();
    await hit.waitFor();
    assert.match(await palette.locator('.palette-status').innerText(), /Digest prefix/);
    await shot('ux13-palette-search');
    assert.match(await palette.locator('[role=option][aria-selected=true]').innerText(), /GET \/admin\/users/);
    await page.keyboard.press('Enter');
    await page.locator('.http-detail-head code', {hasText: config.a}).waitFor();
    assert.equal(await page.getByRole('tab', {name: 'Detail'}).getAttribute('aria-selected'), 'true');
    checks.push(`Digest-prefix search in the palette opened the transaction detail in ${Date.now() - t0} ms`);

    // Text search reaches findings.
    await page.keyboard.press('Control+k');
    await page.keyboard.type('guests');
    // The seeded arena's finding (a reused stack may hold other arenas with it).
    await palette.getByRole('option', {name: new RegExp(`Admin user list readable by guests.*${config.arena}`)}).waitFor();
    await page.keyboard.press('Escape');
    checks.push('Text search finds the finding by a word in its title');

    assert.deepEqual(errors, []);
    console.log(JSON.stringify({ok: true, checks}, null, 1));
  } catch (error) {
    await shot('ux13-failure');
    console.log(JSON.stringify({ok: false, checks, errors, error: String(error)}, null, 1));
    process.exitCode = 1;
  } finally {
    await browser.close();
  }
})();
