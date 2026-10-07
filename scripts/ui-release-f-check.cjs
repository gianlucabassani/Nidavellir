// Release F checks: tidy tool row and lifecycle text, monitor signals row.
// Arena and evidence projections are mocked; nothing is sent to the service.
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

(async () => {
  const browser = await chromium.launch({ headless: true, executablePath: process.env.NV_CHROMIUM_PATH || undefined, args: ['--no-sandbox'] });
  const page = await (await browser.newContext({ viewport: { width: 1440, height: 1000 } })).newPage();
  const errors = [];
  page.on('pageerror', (error) => errors.push(String(error)));
  await page.goto(baseURL + '/console');
  if (page.url().includes('/login')) {
    await page.locator('input[name="username"]').fill(process.env.NV_UI_USERNAME || 'admin');
    await page.locator('input[name="password"]').fill(process.env.NV_UI_PASSWORD || 'nidavellir');
    await page.getByRole('button', { name: 'Sign in' }).click();
    await page.waitForLoadState('networkidle');
  }
  const base = await page.evaluate(async (id) => (await fetch(`/api/console/arenas/${id}`)).json(), arenaId);
  let record = { state: 'destroyed', reset: { status: 'unsupported', reason: 'missing_immutable_inputs_or_readiness_policy' } };
  let signals = [];
  await page.route((url) => url.pathname === `/api/console/arenas/${arenaId}`, (route) => route.fulfill({ json: { ...base, ...record } }));
  await page.route((url) => url.pathname === `/api/console/arenas/${arenaId}/evidence`, (route) =>
    route.fulfill({ json: { artifacts: [], validations: [], transactions: [], signals, observed_at: new Date().toISOString() } }),
  );

  // 1. The tool row has no loose "Tools for" caption.
  await page.goto(baseURL + arenaPath);
  await page.locator('.forge-toolbelt').waitFor();
  check('no "Tools for" caption', !/Tools for/.test(await page.locator('.forge-toolbelt').innerText()));

  // 2. Reset availability is explained inside Arena actions, not as loose text.
  const lifecycle = page.locator('.forge-lifecycle');
  const closedText = await lifecycle.innerText();
  check('no loose reset reason beside the buttons', !/missing|Reset unsupported/i.test(closedText), closedText);
  await page.getByText('Arena actions').click();
  const menu = await page.locator('.forge-lifecycle-menu').innerText();
  check('menu names the reset action', /Reset arena/.test(menu), menu);
  check('menu gives readable reason', /Unavailable: missing immutable inputs or readiness policy/.test(menu), menu);

  // 3. Monitor signals: empty state, then count, latest and expandable list.
  check('monitor row empty state', /No monitor signals recorded/.test(await page.locator('.forge-monitor').innerText()));
  signals = [
    { kind: 'http_error', node: 'victim', severity: 'high', summary: 'SQL error pattern in response', ts: '2026-10-02T10:42:00Z' },
    { kind: 'auth', node: 'victim', severity: 'medium', summary: 'Repeated failed logins', ts: '2026-10-02T10:40:00Z' },
    { kind: 'process', node: 'attacker', severity: 'low', summary: 'New listener on 4444', ts: '2026-10-02T10:30:00Z' },
  ];
  record = { state: 'active', budget: { remaining: 42, cap: 50, gate: 'open' }, reset: { status: 'eligible', reason: null } };
  await page.goto(baseURL + arenaPath);
  await page.locator('.forge-monitor').waitFor();
  await page.waitForTimeout(300);
  const summary = await page.locator('.forge-monitor summary').innerText();
  check('monitor count', /3 signals/.test(summary), summary);
  check('latest signal shown', /SQL error pattern in response/.test(summary), summary);
  await page.locator('.forge-monitor summary').click();
  check('signals listed when expanded', (await page.locator('.forge-monitor .forge-signal').count()) === 3);
  check('severity shown', /high/i.test(await page.locator('.forge-monitor .forge-signal').first().innerText()));

  check('no page errors', errors.length === 0, errors.join('; '));
  await browser.close();
  if (failures.length) {
    console.log(`FAIL ${failures.length}/${checks}`);
    for (const failure of failures) console.log(' - ' + failure);
    process.exit(1);
  }
  console.log(`PASS ${checks}/${checks} release F checks`);
})().catch((error) => { console.error(String(error).split('\n')[0]); process.exit(1); });
