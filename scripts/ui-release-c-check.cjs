// Release C checks: Forge is the single Arena home and carries the Overview's unique content.
// Arena records and the reset response are mocked; no lifecycle request reaches the service.
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
  const browser = await chromium.launch({
    headless: true,
    executablePath: process.env.NV_CHROMIUM_PATH || undefined,
    args: ['--no-sandbox'],
  });
  const context = await browser.newContext({ viewport: { width: 1440, height: 900 } });
  const page = await context.newPage();
  const errors = [];
  page.on('pageerror', (error) => errors.push(String(error)));
  await page.goto(baseURL + '/console');
  if (page.url().includes('/login')) {
    await page.locator('input[name="username"]').fill(process.env.NV_UI_USERNAME || 'admin');
    await page.locator('input[name="password"]').fill(process.env.NV_UI_PASSWORD || 'nidavellir');
    await page.getByRole('button', { name: 'Sign in' }).click();
    await page.waitForLoadState('networkidle');
  }

  // 1. One Arena home: the plain URL and every tool use the rail; no tab strip or second overview.
  for (const query of ['', '?tab=forge', '?tab=http', '?tab=findings']) {
    await page.goto(baseURL + arenaPath + query);
    await page.locator('.arena-tool-rail').waitFor();
    await page.waitForTimeout(250);
    const m = await page.evaluate(() => ({
      tabs: document.querySelectorAll('.arena-tabs').length,
      forge: document.querySelectorAll('.forge-workbench').length,
      legacyOverview: document.querySelectorAll('.arena-work-grid').length,
      forgePreviewText: /Forge preview/.test(document.querySelector('main').innerText),
    }));
    check(`${query || 'plain URL'} has no tab strip`, m.tabs === 0);
    check(`${query || 'plain URL'} has no old overview grid`, m.legacyOverview === 0);
    check(`${query || 'plain URL'} has no "Forge preview" label`, !m.forgePreviewText);
    if (query === '' || query === '?tab=forge') check(`${query || 'plain URL'} opens the Forge view`, m.forge === 1);
  }

  // Mocked arena projections.
  let record = null;
  await page.route(
    (url) => url.pathname === `/api/console/arenas/${arenaId}`,
    async (route) => {
      const response = await route.fetch();
      const arena = await response.json();
      await route.fulfill({ json: { ...arena, ...record } });
    },
  );
  let lifecyclePosts = 0;
  await page.route('**/api/console/arenas/*/lifecycle', (route) => {
    lifecyclePosts++;
    return route.fulfill({ json: { replacement_id: 'replacement-fixture-123' } });
  });

  // 2. Recent findings with verdicts and the PoC job count appear in the Forge record row.
  record = {
    state: 'active',
    budget: { remaining: 42, cap: 50, gate: 'open' },
    reset: { status: 'eligible', reason: null },
    findings: [{ id: 'f1', title: 'Cross-account grant', verdict: 'confirmed' }],
    poc_jobs: [{ id: 'j1', status: 'succeeded' }, { id: 'j2', status: 'failed' }],
  };
  await page.goto(baseURL + arenaPath);
  await page.locator('.forge-workbench').waitFor();
  const proof = await page.locator('.forge-proof').innerText();
  check('record row lists finding title', /Cross-account grant/.test(proof), proof);
  check('record row shows finding verdict', /confirmed/i.test(proof), proof);
  check('record row shows PoC job count', /PoC jobs\s*2/.test(proof), proof);

  // 3. Reset result and replacement link are shown after a confirmed reset.
  await page.getByText('Arena actions').click();
  await page.getByRole('button', { name: 'Reset arena' }).click();
  await page.getByRole('button', { name: 'Confirm reset' }).click();
  await page.locator('.gate-message').waitFor();
  const message = await page.locator('.gate-message').innerText();
  const link = await page.locator('.gate-message a').getAttribute('href');
  check('reset accepted message visible', /Reset accepted by the service/.test(message), message);
  check('replacement arena link', (link || '').includes('replacement-fixture-123'), String(link));
  check('exactly one mocked lifecycle request', lifecyclePosts === 1, String(lifecyclePosts));

  // 4. A blocked reset explains why, even when no reset control is offered.
  record = {
    state: 'destroyed',
    reset: { status: 'unavailable', reason: 'the recipe has no reset strategy' },
    findings: [],
    poc_jobs: [],
  };
  await page.goto(baseURL + arenaPath);
  await page.locator('.forge-workbench').waitFor();
  await page.getByText('Arena actions').click();
  const lifecycle = await page.locator('.forge-lifecycle-menu').innerText();
  check('blocked reset reason shown', /Reset arena[\s\S]*Unavailable: the recipe has no reset strategy/.test(lifecycle), lifecycle);

  // 5. The planned fuzzing tile is gone.
  check('no planned fuzz tile', !(await page.locator('main').innerText()).includes('Fuzz'));

  check('no page errors', errors.length === 0, errors.join('; '));
  await browser.close();
  if (failures.length) {
    console.log(`FAIL ${failures.length}/${checks}`);
    for (const failure of failures) console.log(' - ' + failure);
    process.exit(1);
  }
  console.log(`PASS ${checks}/${checks} release C checks`);
})().catch((error) => {
  console.error(error);
  process.exit(1);
});
