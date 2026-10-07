// Release G stepper checks: research intake steps, purpose meanings. The preview is
// mocked and launch is never clicked; nothing is deployed. Optional argv[2] saves renders.
const { chromium } = require(process.env.NV_PLAYWRIGHT_MODULE || 'playwright');
const out = process.argv[2] || '';
const base = process.env.NV_UI_URL || 'http://127.0.0.1:5000'; const fails = []; let n = 0;
const check = (l, ok, d = '') => { n++; if (!ok) fails.push(l + (d ? ': ' + d : '')); };
(async () => {
  const b = await chromium.launch({ headless: true, executablePath: process.env.NV_CHROMIUM_PATH, args: ['--no-sandbox'] });
  const ctx = await b.newContext({ viewport: { width: 1440, height: 1000 } });
  const p = await ctx.newPage(); const errs = []; p.on('pageerror', (e) => errs.push(String(e)));
  let previewCalls = 0, launchCalls = 0;
  await ctx.route('**/api/console/research/preview', (r) => { previewCalls++; r.fulfill({ json: {
    valid: true, errors: [], warnings: ['Auto-build disabled: no Dockerfile found'], summary: { name: 'acme-notes' },
    topology: { nodes: [{ name: 'attacker', kind: 'foothold', role: 'attacker', ports: [] }, { name: 'sut', kind: 'target', role: 'api', ports: [8000] }],
      segments: [{ name: 'lab', nodes: ['attacker', 'sut'] }], egress: 'blocked' },
    resolved_ref: '3f9c2a1e7b4d5c6a8e9f0b1c2d3e4f5a6b7c8d9e', runtime_ref: null,
    introspection: { build_system: 'python' }, build_plan: { strategy: 'pip install', auto_build: false } } }); });
  await ctx.route('**/api/console/research/launch', (r) => { launchCalls++; r.abort(); });
  await p.goto(base + '/console');
  if (p.url().includes('/login')) { await p.fill('input[name="username"]', 'admin'); await p.fill('input[name="password"]', 'nidavellir'); await p.click('button:has-text("Sign in")'); await p.waitForLoadState('networkidle'); }
  await p.evaluate(() => localStorage.setItem('nidavellir-theme', 'day'));
  await p.goto(base + '/console/research/new'); await p.waitForTimeout(400);
  check('three steps', (await p.locator('.intake-steps li').count()) === 3);
  if (out) await p.screenshot({ path: `${out}/stepper-1.png`, fullPage: true });
  await p.click('button:has-text("Next")');
  check('blocked without required fields', (await p.locator('.intake-steps li.current').innerText()).includes('Target'));
  await p.fill('input[name="instance_id"]', 'acme-notes');
  await p.fill('input[name="repo"]', 'https://github.com/acme/notes');
  await p.fill('input[name="ports"]', '8000');
  await p.click('button:has-text("Next")');
  check('advanced to step 2', (await p.locator('.intake-steps li.current').innerText()).includes('Consent'));
  if (out) await p.screenshot({ path: `${out}/stepper-2.png`, fullPage: true });
  await p.click('button:has-text("Review target")');
  check('blocked without confirmation', previewCalls === 0 && (await p.locator('.intake-steps li.current').innerText()).includes('Consent'));
  await p.check('input[name="authorization_confirmed"]');
  await p.click('button:has-text("Review target")');
  await p.locator('.intake-review svg.topology-graph').waitFor({ timeout: 5000 }).catch(() => {});
  check('review ran once', previewCalls === 1, String(previewCalls));
  check('forge map in review', (await p.locator('.intake-review svg.topology-graph').count()) === 1);
  await p.waitForTimeout(1200);
  check('launch enabled', await p.locator('button:has-text("Launch research")').isEnabled());
  if (out) await p.screenshot({ path: `${out}/stepper-3.png`, fullPage: true });
  await p.click('.intake-steps li:first-child button');
  check('back to step 1 keeps values', (await p.inputValue('input[name="repo"]')) === 'https://github.com/acme/notes');
  check('no launch sent', launchCalls === 0);
  await p.goto(base + '/console/research/new?layout=form'); await p.waitForTimeout(300);
  check('single-page form still available', (await p.locator('.intake-steps').count()) === 0 && (await p.locator('input[name="repo"]').isVisible()));
  await p.goto(base + '/console/arenas/new'); await p.waitForTimeout(500);
  const hint = await p.locator('.field-hint').first().innerText().catch(() => '');
  check('purpose meaning shown', /weaknesses/.test(hint), hint);
  check('manual research label', (await p.locator('option[value="research"]').innerText()) === 'Manual research');
  for (const w of [390, 1024]) { await p.setViewportSize({ width: w, height: 900 }); await p.goto(base + '/console/research/new'); await p.waitForTimeout(300);
    const ov = await p.evaluate(() => document.documentElement.scrollWidth - innerWidth); check(`no overflow @${w}`, ov <= 0, String(ov)); if (w === 390) if (out) await p.screenshot({ path: `${out}/stepper-390.png`, fullPage: true }); }
  check('no page errors', errs.length === 0, errs.join(';'));
  if (fails.length) process.exitCode = 1;
  console.log(fails.length ? `FAIL ${fails.length}/${n}\n - ${fails.join('\n - ')}` : `PASS ${n}/${n}`);
  await b.close();
})();
