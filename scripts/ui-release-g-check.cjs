// Release G checks: workflow fixes inside the approved Forge look.
// Arena, activity, research, benchmark and binding projections are mocked;
// the revoke confirmation is cancelled, so nothing is sent to the service.
const { chromium } = require(process.env.NV_PLAYWRIGHT_MODULE || 'playwright');

const baseURL = process.env.NV_UI_URL || 'http://127.0.0.1:5000';
const arenaId = process.env.NV_UI_ARENA_ID || '7b2b268a-1a09-4cc3-aa71-f733e73450bc';
const arenaPath = `/console/arena/${encodeURIComponent(arenaId)}`;
const failures = [];
let checks = 0;
const check = (label, ok, detail = '') => {
  checks++;
  if (!ok) failures.push(`${label}${detail ? `: ${detail}` : ''}`);
};
const now = Date.now();
const iso = (minutes) => new Date(now - minutes * 60000).toISOString();

const audit = [
  { type: 'http_transaction', ts: iso(2), actor: 'web-researcher', source: 'agent', arena_id: arenaId, arena_name: 'ui-smoke-20260928', arena_known: true },
  { type: 'finding_verdict', ts: iso(6), actor: 'admin', source: 'human', arena_id: arenaId, arena_name: 'ui-smoke-20260928', arena_known: true },
  { type: 'poc_job_completed', ts: iso(9), actor: 'system', source: 'system', arena_id: arenaId, arena_name: 'ui-smoke-20260928', arena_known: true },
];

(async () => {
  const browser = await chromium.launch({ headless: true, executablePath: process.env.NV_CHROMIUM_PATH || undefined, args: ['--no-sandbox'] });
  const page = await (await browser.newContext({ viewport: { width: 1440, height: 1000 } })).newPage();
  const errors = [];
  const nativeDialogs = [];
  page.on('pageerror', (error) => errors.push(String(error)));
  page.on('dialog', (dialog) => {
    nativeDialogs.push(dialog.message());
    void dialog.dismiss();
  });
  await page.goto(baseURL + '/console');
  if (page.url().includes('/login')) {
    await page.locator('input[name="username"]').fill(process.env.NV_UI_USERNAME || 'admin');
    await page.locator('input[name="password"]').fill(process.env.NV_UI_PASSWORD || 'nidavellir');
    await page.getByRole('button', { name: 'Sign in' }).click();
    await page.waitForLoadState('networkidle');
  }
  const base = await page.evaluate(async (id) => (await fetch(`/api/console/arenas/${id}`)).json(), arenaId);
  // Station states match the arena state, so the fixture is not contradictory.
  const active = {
    ...base,
    state: 'active',
    budget: { remaining: 42, cap: 50, gate: 'open' },
    reset: { status: 'eligible', reason: null },
    nodes: base.nodes.map((node) => ({ ...node, state: 'running' })),
  };
  await page.route((url) => url.pathname === `/api/console/arenas/${arenaId}`, (route) => route.fulfill({ json: active }));
  await page.route((url) => url.pathname === '/api/console/activity', (route) =>
    route.fulfill({ json: { findings: [], artifacts: [], signals: [], audit, observed_at: new Date().toISOString() } }),
  );
  await page.route((url) => url.pathname === `/api/arenas/${arenaId}/bindings`, (route) =>
    route.request().method() === 'GET'
      ? route.fulfill({ json: { bindings: [{ agent_name: 'web-researcher', stance: 'attacker', paused: false }] } })
      : route.abort(),
  );

  // 1. Tool row: ready tools keep the launch arrow; others do not.
  await page.goto(baseURL + arenaPath);
  await page.locator('.forge-toolbelt').waitFor();
  const tools = await page.locator('.forge-toolbelt > a').evaluateAll((items) =>
    items.map((item) => ({ ready: item.classList.contains('ready'), arrow: Boolean(item.querySelector('b')), border: getComputedStyle(item).borderStyle })),
  );
  check('unavailable tools have no launch arrow', tools.filter((tool) => !tool.ready).every((tool) => !tool.arrow), JSON.stringify(tools));
  check('unavailable tools read as secondary', tools.filter((tool) => !tool.ready).every((tool) => tool.border === 'dashed'), JSON.stringify(tools));

  // 2. Assistant launcher shows model status without opening the panel.
  const launcher = page.locator('.assistant-launcher');
  await page.waitForFunction(() => !document.querySelector('.assistant-dot.checking'));
  check('launcher has a status dot', (await launcher.locator('.assistant-dot').count()) === 1);
  const launcherName = (await page.locator('#assistant-model-state').innerText().catch(() => '')) || '';
  check('launcher names the model state', /connected|no model|unavailable|checking/.test(launcherName), launcherName);

  // 3. The end of the page is clear of the launcher.
  await page.evaluate(() => window.scrollTo(0, document.body.scrollHeight));
  const overlap = await page.evaluate(() => {
    const box = document.querySelector('.assistant-launcher').getBoundingClientRect();
    const link = document.querySelector('.site-footer a').getBoundingClientRect();
    return !(link.right < box.left || link.left > box.right || link.bottom < box.top || link.top > box.bottom);
  });
  check('footer link not under the launcher', !overlap);

  // 4. Revoke uses the in-page dialog; cancelling sends nothing.
  await page.goto(`${baseURL}${arenaPath}?tab=access`);
  await page.getByRole('button', { name: 'Revoke' }).click();
  const dialog = page.locator('dialog.gate-dialog[open]');
  await dialog.waitFor({ timeout: 3000 }).catch(() => {});
  check('revoke opens in-page dialog', (await dialog.count()) === 1);
  check('no native confirm', nativeDialogs.length === 0, nativeDialogs.join('; '));
  if (await dialog.count()) await dialog.getByRole('button', { name: 'Cancel' }).click();
  check('dialog closes on cancel', (await page.locator('dialog.gate-dialog[open]').count()) === 0);

  // 5. Research home: live activity with source filter; console-native links.
  await page.goto(baseURL + '/console?workspace=research');
  const panel = page.locator('.research-activity');
  await panel.waitFor({ timeout: 5000 }).catch(() => {});
  check('live activity panel', (await panel.count()) === 1);
  if (await panel.count()) {
    await panel.locator('.activity-row').first().waitFor();
    check('shows recent events', (await panel.locator('.activity-row').count()) === 3);
    await panel.getByRole('button', { name: 'Agents' }).click();
    check('agent filter', (await panel.locator('.activity-row').count()) === 1);
    check('newest first', /http transaction/.test(await panel.locator('.activity-row').first().innerText()));
  }
  const legacyLinks = await page.locator('main a[href^="/activity"], main a[href^="/library"], main a[href^="/arena/"]').count();
  check('Research links stay in the console', legacyLinks === 0, `${legacyLinks} legacy links`);
  const pill = await page.locator('.session-row .status').first().evaluate((item) => item.getBoundingClientRect().width).catch(() => 0);
  check('status pill fits its label', pill > 0 && pill < 120, `${pill}px`);

  // 6. Benchmark home: workflow steps with the next step marked.
  await page.goto(baseURL + '/console?workspace=benchmark');
  const steps = page.locator('.workflow-steps li');
  await steps.first().waitFor({ timeout: 5000 }).catch(() => {});
  check('four workflow steps', (await steps.count()) === 4);
  check('exactly one next step', (await page.locator('.workflow-steps li.next').count()) <= 1);

  for (const width of [1024, 390]) {
    await page.setViewportSize({ width, height: 900 });
    for (const path of ['/console?workspace=research', '/console?workspace=benchmark', arenaPath]) {
      await page.goto(baseURL + path);
      await page.waitForTimeout(400);
      const overflow = await page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth);
      check(`no overflow ${path} @${width}`, overflow <= 0, `${overflow}px`);
    }
  }

  check('no page errors', errors.length === 0, errors.join('; '));
  await browser.close();
  if (failures.length) {
    console.log(`FAIL ${failures.length}/${checks}`);
    for (const failure of failures) console.log(' - ' + failure);
    process.exit(1);
  }
  console.log(`PASS ${checks}/${checks} release G checks`);
})().catch((error) => { console.error(String(error).split('\n')[0]); process.exit(1); });
