// Release H checks: completed console menus (All arenas, All evaluations,
// Score & trace, Service forwards, agent connect recipe, Activity filters,
// capacity, Forge sign-in). Destructive actions are cancelled or mocked;
// nothing is destroyed, removed or opened on the service.
const { chromium } = require(process.env.NV_PLAYWRIGHT_MODULE || 'playwright');

const base = process.env.NV_UI_URL || 'http://127.0.0.1:5000';
const arenaId = process.env.NV_UI_ARENA_ID || '7b2b268a-1a09-4cc3-aa71-f733e73450bc';
const failures = [];
let checks = 0;
const check = (label, ok, detail = '') => {
  checks++;
  if (!ok) failures.push(`${label}${detail ? `: ${detail}` : ''}`);
};

(async () => {
  const browser = await chromium.launch({ headless: true, executablePath: process.env.NV_CHROMIUM_PATH || undefined, args: ['--no-sandbox'] });
  const context = await browser.newContext({ viewport: { width: 1440, height: 1000 } });
  const page = await context.newPage();
  const errors = [];
  const mutations = [];
  page.on('pageerror', (error) => errors.push(String(error)));
  page.on('dialog', (dialog) => { errors.push(`native dialog: ${dialog.message()}`); void dialog.dismiss(); });
  // Any destructive or lease request is recorded and refused.
  await context.route(/\/api\/console\/(archive|arenas\/[^/]+\/(lifecycle|forwards))/, (route) => {
    if (route.request().method() === 'POST') { mutations.push(route.request().url()); return route.abort(); }
    return route.fallback();
  });

  // 1. Forge sign-in keeps the form contract.
  await page.goto(base + '/login');
  check('sign-in plate', (await page.locator('main.plate').count()) === 1);
  check('csrf field', (await page.locator('input[name="csrf_token"]').count()) === 1);
  await page.locator('input[name="username"]').fill(process.env.NV_UI_USERNAME || 'admin');
  await page.locator('input[name="password"]').fill(process.env.NV_UI_PASSWORD || 'nidavellir');
  await page.getByRole('button', { name: 'Sign in' }).click();
  await page.waitForLoadState('networkidle');
  check('signed in', !page.url().includes('/login'), page.url());

  // 2. Library menu reaches the new list pages.
  await page.goto(base + '/console?workspace=research');
  await page.locator('.tools-menu summary').click();
  const library = await page.locator('.tools-menu a').allInnerTexts();
  check('library lists arenas and evaluations', library.includes('All arenas') && library.includes('All evaluations'), library.join(','));
  check('no legacy View all links', (await page.locator('main a[href="/engagements"], main a[href^="/evaluations"]').count()) === 0);
  check('capacity panel', (await page.locator('.research-capacity').count()) === 1);

  // 3. All arenas: filters, and confirm dialogs that cancel cleanly.
  await page.goto(base + '/console/arenas');
  await page.locator('.arena-list-row, .message-panel, .empty').first().waitFor();
  const total = await page.locator('.arena-list-row').count();
  await page.getByRole('button', { name: /^Archived/ }).click();
  const archivedRows = await page.locator('.arena-list-row').count();
  check('archived filter narrows', archivedRows <= total, `${archivedRows}/${total}`);
  const remove = page.locator('.arena-list-row button', { hasText: 'Remove' }).first();
  if (await remove.count()) {
    await remove.click();
    check('remove asks in-page', (await page.locator('dialog.gate-dialog[open]').count()) === 1);
    await page.locator('dialog.gate-dialog[open]').getByRole('button', { name: 'Cancel' }).click();
  }
  check('cancel sent nothing', mutations.length === 0, mutations.join(','));

  // 4. All evaluations lists comparisons with a state filter.
  await page.goto(base + '/console/evaluations');
  check('evaluations page', /All evaluations/.test(await page.locator('h1').innerText()));

  // 5. Activity verdict and source chips.
  await page.goto(base + '/console/activity?section=audit');
  const chips = page.locator('.filter-chips button');
  await chips.first().waitFor();
  check('source chips', (await chips.count()) === 4);
  const before = await page.locator('.activity-audit-row').count();
  await chips.nth(3).click();
  const systemOnly = await page.locator('.activity-audit-row .activity-source').allInnerTexts();
  check('system filter', systemOnly.every((text) => /system/i.test(text)) && systemOnly.length <= before);

  // 6. Arena Score & trace, forwards and connect recipe.
  await page.goto(`${base}/console/arena/${encodeURIComponent(arenaId)}?tab=score`);
  await page.locator('.record-score').waitFor();
  check('score panel', (await page.locator('.record-score').count()) === 1);
  const reveal = page.locator('.reveal-toggle input');
  if (await reveal.count()) {
    check('ground truth hidden first', (await page.locator('.challenge-row').count()) === 0);
    await reveal.check();
    check('reveal shows challenges', (await page.locator('.challenge-row').count()) > 0);
  }
  await page.goto(`${base}/console/arena/${encodeURIComponent(arenaId)}?tab=forwards`);
  await page.locator('.record-grid').waitFor({ timeout: 5000 }).catch(() => {});
  check('forwards panel', /service forward/i.test(await page.locator('main').innerText()));
  await page.goto(`${base}/console/arena/${encodeURIComponent(arenaId)}?tab=access`);
  await page.locator('.access-connect').waitFor({ timeout: 5000 }).catch(() => {});
  check('connect recipe', (await page.locator('.access-connect .copy-field').count()) === 3);

  for (const width of [390, 1024]) {
    await page.setViewportSize({ width, height: 900 });
    for (const path of ['/console/arenas', '/console/evaluations', `/console/arena/${encodeURIComponent(arenaId)}?tab=score`]) {
      await page.goto(base + path);
      await page.waitForTimeout(300);
      const overflow = await page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth);
      check(`no overflow ${path} @${width}`, overflow <= 0, `${overflow}px`);
    }
  }
  check('no mutations sent', mutations.length === 0, mutations.join(','));
  check('no page errors', errors.length === 0, errors.join('; '));
  await browser.close();
  if (failures.length) {
    console.log(`FAIL ${failures.length}/${checks}`);
    for (const failure of failures) console.log(' - ' + failure);
    process.exit(1);
  }
  console.log(`PASS ${checks}/${checks} release H checks`);
})().catch((error) => { console.error(String(error).split('\n')[0]); process.exit(1); });
