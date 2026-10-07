// Release D checks: layered topology for N-node arenas and tester-facing station facts.
// Arena records are mocked; nothing is launched and no credentials are involved.
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

const pivot = {
  state: 'active',
  nodes: [
    station('attacker', { foothold: true, role: 'attacker', segments: ['dmz'], ready: null, private_ip: '10.0.1.2' }),
    station('web', { role: 'web', declared_ports: [80, 443], service_count: 2, web_capable: true, segments: ['dmz', 'internal'], private_ip: '10.0.1.3' }),
    station('db', { role: 'database', declared_ports: [5432], service_count: 1, segments: ['internal'] }),
    station('files', { declared_ports: [445], service_count: 1, segments: ['internal', 'mgmt'] }),
    station('admin', { declared_ports: [22], service_count: 1, segments: ['mgmt'] }),
    station('orphan', { segments: [] }),
  ],
  topology: {
    segments: [
      { name: 'dmz', nodes: ['attacker', 'web'] },
      { name: 'internal', nodes: ['web', 'db', 'files'] },
      { name: 'mgmt', nodes: ['files', 'admin'] },
    ],
    unsegmented: ['orphan'],
  },
  capabilities: {
    http: { state: 'ready', reason: 'declared_web_target' },
    browser: { state: 'ready', reason: 'declared_web_target' },
    poc: { state: 'unsupported', reason: 'provider_not_implemented' },
  },
};
const big = {
  state: 'active',
  nodes: [
    station('kali', { foothold: true, role: 'attacker', segments: ['edge'] }),
    ...Array.from({ length: 13 }, (_, i) => station(`host-${i + 1}`, { segments: [i < 6 ? 'edge' : 'core'], declared_ports: [8000 + i], service_count: 1 })),
  ],
  topology: {
    segments: [
      { name: 'edge', nodes: ['kali', 'host-1', 'host-2', 'host-3', 'host-4', 'host-5', 'host-6'] },
      { name: 'core', nodes: ['host-6', ...Array.from({ length: 7 }, (_, i) => `host-${i + 7}`)] },
    ],
    unsegmented: [],
  },
  capabilities: null,
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

  // Real two-station record still reads attacker -> network -> target.
  await page.goto(baseURL + arenaPath);
  await page.locator('.topology-station').first().waitFor();
  const real = await page.evaluate(() => {
    const x = (label) => [...document.querySelectorAll('.topology-station, .topology-hub')].find((g) => g.querySelector('title')?.textContent.startsWith(label))?.getBoundingClientRect().left;
    return { attacker: x('attacker'), hub: x('Network lab'), victim: x('victim') };
  });
  check('two-station order attacker < lab < victim', real.attacker < real.hub && real.hub < real.victim, JSON.stringify(real));
  const realDetail = await page.locator('.topology-station-detail').allTextContents();
  check('target station shows role and declared port', realDetail.some((t) => /Target · :80/.test(t)), realDetail.join(' | '));

  let record = pivot;
  await page.route((url) => url.pathname === `/api/console/arenas/${arenaId}`, async (route) => {
    const arena = await (await route.fetch()).json();
    await route.fulfill({ json: { ...arena, ...record } });
  });

  // Six-station pivot: columns follow hops from the foothold.
  await page.goto(baseURL + arenaPath);
  await page.locator('.topology-station').first().waitFor();
  await page.waitForTimeout(300);
  const geo = await page.evaluate(() => {
    const box = (label) => [...document.querySelectorAll('.topology-station, .topology-hub')].find((g) => g.querySelector('title')?.textContent.startsWith(label))?.getBoundingClientRect();
    const scroll = document.querySelector('.topology-graph-scroll');
    const widths = [...document.querySelectorAll('.topology-station > path:first-of-type')].map((p) => Math.round(p.getBoundingClientRect().width));
    const left = (label) => box(label)?.left;
    return {
      order: ['attacker:', 'Network dmz', 'web:', 'Network internal', 'db:', 'Network mgmt', 'admin:'].map(left),
      files: left('files:'), db: left('db:'),
      widths: [...new Set(widths)],
      scrolls: scroll.scrollWidth > scroll.clientWidth,
      overflow: document.documentElement.scrollWidth > innerWidth,
      labels: [...document.querySelectorAll('.topology-column-label')].map((t) => t.textContent),
      unlinked: document.querySelector('.topology-unlinked')?.textContent || '',
    };
  });
  check('pivot columns ordered by hop', geo.order.every((x, i) => typeof x === 'number' && (i === 0 || x > geo.order[i - 1])), JSON.stringify(geo.order));
  check('host on two networks sits in the second-hop column', Math.abs(geo.files - geo.db) < 2, `${geo.files} vs ${geo.db}`);
  check('stations keep one width', geo.widths.length === 1 && geo.widths[0] >= 180 && geo.widths[0] <= 188, JSON.stringify(geo.widths));
  check('wide topology scrolls inside its panel', geo.scrolls);
  check('no document overflow', !geo.overflow);
  check('pivot and target labels truthful', JSON.stringify(geo.labels.filter((l) => l.endsWith('HOST'))) === JSON.stringify(['PIVOT / HOST', 'PIVOT / HOST', 'TARGET / HOST']), geo.labels.join(','));
  check('scroll hint shown when map continues', await page.locator('.topology-scroll-hint').isVisible());
  check('unlinked station listed', /orphan/.test(geo.unlinked), geo.unlinked);

  // Inspector facts and tool availability for the selected station.
  const inspector = () => page.locator('.forge-inspector').innerText();
  const tools = async () => (await page.locator('.forge-toolbelt a').evaluateAll((links) => links.map((l) => `${l.innerText.split('\n')[0]} ${l.getAttribute('aria-label')} ${l.getAttribute('title')}`))).join(' | ');
  await page.locator('.topology-station', { hasText: 'web' }).first().click();
  let text = await inspector();
  check('inspector role', /Web station/.test(text), text);
  check('inspector ports', /:80 :443/.test(text), text);
  check('inspector networks', /dmz, internal/.test(text), text);
  check('inspector private IP', /10\.0\.1\.3/.test(text), text);
  check('HTTP ready for web', /Use web in HTTP/.test(await tools()), await tools());
  check('PoC unavailable with reason', /PoC: Unavailable here: this provider does not support it/.test(await tools()), await tools());
  await page.locator('.topology-station', { hasText: 'db' }).first().click();
  text = await inspector();
  check('HTTP not offered for non-web station', /HTTP: No declared web service/.test(await tools()), await tools());
  await page.locator('.topology-station', { hasText: 'attacker' }).first().click();
  text = await inspector();
  check('foothold explained', /Attacker foothold: your entry point/.test(text) && /Attacker station, not a target/.test(await tools()), text);
  check('no shell command exposed', !/ssh /i.test(await page.locator('main').innerText()));

  // Fourteen stations render without errors; missing capability data degrades gracefully.
  record = big;
  await page.goto(baseURL + arenaPath);
  await page.locator('.topology-station').first().waitFor();
  check('fourteen stations drawn', (await page.locator('.topology-station').count()) === 14);
  await page.locator('.topology-station', { hasText: 'host-9' }).first().click();
  text = await inspector();
  check('eligible without capability report', /Use host-9 in PoC/.test(await tools()), await tools());

  check('no page errors', errors.length === 0, errors.join('; '));
  await browser.close();
  if (failures.length) {
    console.log(`FAIL ${failures.length}/${checks}`);
    for (const failure of failures) console.log(' - ' + failure);
    process.exit(1);
  }
  console.log(`PASS ${checks}/${checks} release D checks`);
})().catch((error) => { console.error(error); process.exit(1); });
