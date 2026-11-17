// Release E checks: explicit target handoff from the Forge map to HTTP, Browser and PoC.
// Arena records are mocked; the check fails if any tool request is sent.
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
const station = (name, extra = {}) => ({
  name, state: 'running', foothold: false, service_count: 0, web_capable: false,
  role: 'victim', image: `${name}:latest`, image_pinned: false, declared_ports: [],
  segments: [], private_ip: null, url: null, ready: true, ...extra,
});
const record = {
  state: 'active',
  provider: 'docker-local',
  budget: { remaining: 42, cap: 50, gate: 'open' },
  nodes: [
    station('attacker', { foothold: true, role: 'attacker', segments: ['dmz'] }),
    station('web', { role: 'web', declared_ports: [80], service_count: 1, web_capable: true, segments: ['dmz', 'internal'] }),
    station('api', { role: 'api', declared_ports: [8080], service_count: 1, web_capable: true, segments: ['internal'] }),
    station('db', { role: 'database', declared_ports: [5432], service_count: 1, segments: ['internal'] }),
  ],
  topology: {
    segments: [
      { name: 'dmz', nodes: ['attacker', 'web'] },
      { name: 'internal', nodes: ['web', 'api', 'db'] },
    ],
    unsegmented: [],
  },
  capabilities: {
    http: { state: 'ready', reason: 'declared_web_target' },
    browser: { state: 'ready', reason: 'declared_web_target' },
    poc: { state: 'ready', reason: 'confined_runner' },
  },
};

(async () => {
  const browser = await chromium.launch({ headless: true, executablePath: process.env.NV_CHROMIUM_PATH || undefined, args: ['--no-sandbox'] });
  const page = await (await browser.newContext({ viewport: { width: 1440, height: 1000 } })).newPage();
  const errors = [];
  const mutations = [];
  page.on('pageerror', (error) => errors.push(String(error)));
  page.on('request', (request) => {
    if (request.method() !== 'GET' && /\/(http\/request|browser\/visit|poc-jobs)/.test(request.url())) mutations.push(request.url());
  });
  await page.goto(baseURL + '/console');
  if (page.url().includes('/login')) {
    await page.locator('input[name="username"]').fill(process.env.NV_UI_USERNAME || 'admin');
    await page.locator('input[name="password"]').fill(process.env.NV_UI_PASSWORD || 'nidavellir');
    await page.getByRole('button', { name: 'Sign in' }).click();
    await page.waitForLoadState('networkidle');
  }
  // Fetch the real record once, then serve the mock without further network races.
  const base = await page.evaluate(async (id) => (await fetch(`/api/console/arenas/${id}`)).json(), arenaId);
  await page.route((url) => url.pathname === `/api/console/arenas/${arenaId}`, (route) =>
    route.fulfill({ json: { ...base, ...record } }),
  );

  // 1. The inspector offers a named, explicit handoff only for eligible tools.
  await page.goto(baseURL + arenaPath);
  await page.locator('.topology-station', { hasText: 'api' }).first().click();
  const httpLink = page.getByRole('link', { name: 'Use api in HTTP' });
  check('HTTP handoff offered for web station', (await httpLink.count()) === 1);
  check('handoff link carries the target', ((await httpLink.getAttribute('href')) || '').includes('tab=http&target=api'));
  await page.locator('.topology-station', { hasText: 'db' }).first().click();
  check('no HTTP handoff for a non-web station', (await page.getByRole('link', { name: 'Use db in HTTP' }).count()) === 0);
  check('PoC handoff offered for db', (await page.getByRole('link', { name: 'Use db in PoC' }).count()) === 1);
  await page.locator('.topology-station', { hasText: 'attacker' }).first().click();
  check('no handoff for the attacker station', (await page.locator('.forge-toolbelt a.ready').count()) === 0);

  // 2. Following the handoff preselects the target and says where it came from.
  await page.locator('.topology-station', { hasText: 'api' }).first().click();
  await page.getByRole('link', { name: 'Use api in HTTP' }).click();
  await page.waitForURL(/tab=http/);
  await page.getByLabel('Target node').waitFor();
  check('HTTP target preselected', (await page.getByLabel('Target node').inputValue()) === 'api');
  check('HTTP shows map origin', /Target from map: api/.test(await page.locator('.map-target').innerText()));

  // 3. Changing the target by hand drops the map origin from the URL and the notice.
  await page.getByLabel('Target node').selectOption('web');
  await page.waitForTimeout(200);
  check('manual change clears target param', !new URL(page.url()).searchParams.has('target'), page.url());
  check('notice removed after manual change', (await page.locator('.map-target').count()) === 0);

  // 4. A target the tool cannot use is refused with a reason, not silently swapped.
  await page.goto(`${baseURL}${arenaPath}?tab=http&target=db`);
  await page.getByLabel('Target node').waitFor();
  check('ineligible map target not selected', (await page.getByLabel('Target node').inputValue()) !== 'db');
  check('ineligible map target explained', /db cannot be used by HTTP/.test(await page.locator('.map-target').innerText()));

  // 5. Browser and PoC honour the handoff too.
  await page.goto(`${baseURL}${arenaPath}?tab=browser&target=api`);
  await page.getByLabel('Target node').waitFor();
  check('Browser target preselected', (await page.getByLabel('Target node').inputValue()) === 'api');
  await page.goto(`${baseURL}${arenaPath}?tab=poc&target=db`);
  await page.getByLabel('HTTP target').waitFor();
  check('PoC target preselected', (await page.getByLabel('HTTP target').inputValue()) === 'db');
  check('PoC shows map origin', /Target from map: db/.test(await page.locator('.map-target').innerText()));

  // 6. No empty band under the workbench row or inside the map, at common widths.
  for (const [label, url, width] of [
    ['mock', `${baseURL}${arenaPath}`, 1440],
    ['mock', `${baseURL}${arenaPath}`, 1280],
  ]) {
    await page.setViewportSize({ width, height: 1000 });
    await page.goto(url);
    await page.locator('.forge-toolbelt').waitFor();
    await page.locator('.topology-station', { hasText: 'api' }).first().click();
    await page.waitForTimeout(300);
    const gap = await page.evaluate(() => {
      const canvas = document.querySelector('.forge-canvas').getBoundingClientRect();
      const belt = document.querySelector('.forge-toolbelt').getBoundingClientRect();
      const graph = document.querySelector('.topology-graph')?.getBoundingClientRect();
      const stations = [...document.querySelectorAll('.topology-station > path:first-of-type')].map((e) => e.getBoundingClientRect());
      const span = Math.max(...stations.map((s) => s.bottom)) - Math.min(...stations.map((s) => s.top));
      return { below: Math.round(canvas.bottom - belt.bottom), insideMap: Math.round((graph?.height || 0) - span) };
    });
    check(`${label} ${width}: no empty band under workbenches (<= 32px)`, gap.below <= 32, JSON.stringify(gap));
    check(`${label} ${width}: map sized to its stations (<= 110px spare)`, gap.insideMap <= 110, JSON.stringify(gap));
  }
  await page.setViewportSize({ width: 1440, height: 1000 });

  check('no tool request was sent', mutations.length === 0, mutations.join(', '));
  check('no page errors', errors.length === 0, errors.join('; '));
  await browser.close();
  if (failures.length) {
    console.log(`FAIL ${failures.length}/${checks}`);
    for (const failure of failures) console.log(' - ' + failure);
    process.exit(1);
  }
  console.log(`PASS ${checks}/${checks} release E checks`);
})().catch((error) => { console.error(error); process.exit(1); });
