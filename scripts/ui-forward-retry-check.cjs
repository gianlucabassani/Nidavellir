// Regression for one forward action across an uncertain response. All console
// API reads and mutations are intercepted; no lease reaches the service.
const assert = require('node:assert/strict');
const { chromium } = require(process.env.NV_PLAYWRIGHT_MODULE || 'playwright');
const base = process.env.NV_UI_URL || 'http://127.0.0.1:5000';
const arena = 'forward-retry-review';
(async () => {
  const browser = await chromium.launch({ headless: true,
    executablePath: process.env.NV_CHROMIUM_PATH || undefined, args: ['--no-sandbox'] });
  try {
    const page = await browser.newPage();
    const calls = [];
    const errors = [];
    page.on('pageerror', error => errors.push(String(error)));
    await page.route('**/api/**', async route => {
      const request = route.request();
      const path = new URL(request.url()).pathname;
      if (path.endsWith('/forwards')) {
        if (request.method() === 'POST') {
          calls.push(request.postDataJSON());
          return route.fulfill({ status: calls.length === 1 ? 502 : 200,
            json: calls.length === 1 ? { error: 'Uncertain response; retry' } : { id: 'lease-1' } });
        }
        return route.fulfill({ json: { state: 'ready', reason: '', footholds: ['kali'],
          services: [{ target: 'api', service: 'http' }, { target: 'api', service: 'other' }], forwards: [] } });
      }
      if (path === `/api/console/arenas/${arena}`) return route.fulfill({ json: {
        id: arena, name: arena, state: 'active', provider: 'docker-local', scenario: 'fixture',
        observed_at: new Date().toISOString(), nodes: [], topology: null, poc_jobs: [], events: [],
        findings: [], monitor: [], budget: {}, research_policy: {}, reset: {}, setup: {},
      } });
      return route.fulfill({ json: {} });
    });
    await page.goto(`${base}/console/arena/${arena}?tab=forwards`);
    if (page.url().includes('/login')) {
      await page.fill('input[name="username"]', process.env.NV_UI_USERNAME || 'admin');
      await page.fill('input[name="password"]', process.env.NV_UI_PASSWORD || 'nidavellir');
      await page.getByRole('button', { name: 'Sign in' }).click();
    }
    const open = page.getByRole('button', { name: 'Open 120-second forward', exact: true });
    await open.click();
    await page.getByRole('status').filter({ hasText: 'Uncertain response; retry' }).waitFor();
    await open.click();
    await page.getByRole('status').filter({ hasText: 'Forward lease opened.' }).waitFor();
    assert.ok(typeof calls[0].idempotency_key === 'string' && calls[0].idempotency_key.length >= 8);
    assert.equal(calls[0].idempotency_key, calls[1].idempotency_key, 'uncertain retry must reuse key');
    await open.click();
    await page.waitForFunction(() => !document.querySelector('.forward-form button').disabled);
    assert.notEqual(calls[1].idempotency_key, calls[2].idempotency_key, 'new confirmed action needs new key');
    await page.locator('.forward-form select').nth(1).selectOption('api:other');
    await open.click();
    await page.waitForFunction(() => !document.querySelector('.forward-form button').disabled);
    assert.notEqual(calls[2].idempotency_key, calls[3].idempotency_key, 'changed destination needs new key');
    assert.equal(calls[3].service_id, 'other');
    assert.deepEqual(errors, []);
    console.log('PASS forward retry: stable key, new action, changed destination, no page errors');
  } finally { await browser.close(); }
})().catch(error => { console.error(error); process.exitCode = 1; });
