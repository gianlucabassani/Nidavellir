// Release B checks: fixed-scale topology, truthful assistant status, launcher clearance.
// Read-only: model connection responses are mocked; nothing is saved or launched.
const { chromium } = require(process.env.NV_PLAYWRIGHT_MODULE || 'playwright');

const baseURL = process.env.NV_UI_URL || 'http://127.0.0.1:5000';
const arenaId = process.env.NV_UI_ARENA_ID || '7b2b268a-1a09-4cc3-aa71-f733e73450bc';
const arenaUrl = `${baseURL}/console/arena/${encodeURIComponent(arenaId)}?tab=forge`;
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

  // 1. Topology stations keep one readable size at every desktop width.
  const sizes = {};
  for (const width of [1024, 1280, 1920]) {
    await page.setViewportSize({ width, height: 1000 });
    await page.goto(arenaUrl);
    await page.locator('.topology-station').first().waitFor();
    await page.waitForTimeout(300);
    sizes[width] = await page.evaluate(() => {
      const station = document.querySelector('.topology-station path').getBoundingClientRect();
      const name = document.querySelector('.topology-station-name').getBoundingClientRect();
      return { w: Math.round(station.width), nameH: Math.round(name.height), overflow: document.documentElement.scrollWidth > innerWidth };
    });
    check(`topology ${width} station name readable (>=13px)`, sizes[width].nameH >= 13, String(sizes[width].nameH));
    check(`topology ${width} no document overflow`, !sizes[width].overflow);
  }
  check('topology station width constant 1024..1920', Math.abs(sizes[1024].w - sizes[1920].w) <= 2, JSON.stringify(sizes));

  // 2. Assistant status line reflects the connection, not just the chat history.
  for (const configured of [true, false]) {
    await page.unroute('**/api/model-connection').catch(() => {});
    await page.route('**/api/model-connection', (route) =>
      route.fulfill({ json: configured ? { configured: true, provider: 'custom', model: 'fixture-model' } : { configured: false } }),
    );
    await page.setViewportSize({ width: 1440, height: 900 });
    await page.goto(arenaUrl);
    await page.getByRole('button', { name: 'Research assistant', exact: true }).click();
    await page.locator('.assistant-progress').waitFor();
    await page.waitForTimeout(300);
    const status = (await page.locator('.assistant-progress').textContent()).trim();
    if (configured) check('assistant status when connected', !/when a model is connected/i.test(status) && /ready/i.test(status), status);
    else check('assistant status when not connected', /connect/i.test(status), status);
  }
  await page.unroute('**/api/model-connection');

  // 3. With the page scrolled to the end, the closed launcher covers no control.
  for (const [width, height] of [[1024, 768], [1440, 900], [390, 844], [320, 700]]) {
    await page.setViewportSize({ width, height });
    await page.goto(arenaUrl);
    await page.locator('.forge-workbench').waitFor();
    await page.evaluate(() => window.scrollTo(0, document.documentElement.scrollHeight));
    await page.waitForTimeout(300);
    const hits = await page.evaluate(() => {
      const launcher = document.querySelector('.assistant-launcher').getBoundingClientRect();
      const overlap = (r) => r.width > 0 && r.height > 0 && r.left < launcher.right && r.right > launcher.left && r.top < launcher.bottom && r.bottom > launcher.top;
      return [...document.querySelectorAll('main a, main button, main summary, main input, main select, main textarea')]
        .filter((el) => el.getClientRects().length && overlap(el.getBoundingClientRect()))
        .map((el) => (el.textContent || el.getAttribute('aria-label') || el.tagName).trim().slice(0, 30));
    });
    check(`launcher clear of controls at end of page ${width}`, hits.length === 0, hits.join(' | '));
  }

  // 4. Below 1280 px the closed launcher is a compact, still-named control.
  for (const width of [1024, 390]) {
    await page.setViewportSize({ width, height: 844 });
    await page.goto(arenaUrl);
    await page.locator('.forge-workbench').waitFor();
    const launcher = page.getByRole('button', { name: 'Research assistant', exact: true });
    const box = await launcher.boundingBox();
    check(`compact launcher at ${width}`, !!box && box.width <= 48 && box.height <= 48, JSON.stringify(box));
  }
  await page.setViewportSize({ width: 1440, height: 900 });
  await page.goto(arenaUrl);
  const wide = await page.getByRole('button', { name: 'Research assistant', exact: true }).boundingBox();
  check('labelled launcher at 1440', !!wide && wide.width > 100, JSON.stringify(wide));

  check('no page errors', errors.length === 0, errors.join('; '));
  await browser.close();
  if (failures.length) {
    console.log(`FAIL ${failures.length}/${checks}`);
    for (const failure of failures) console.log(' - ' + failure);
    process.exit(1);
  }
  console.log(`PASS ${checks}/${checks} release B checks`);
})().catch((error) => {
  console.error(error);
  process.exit(1);
});
