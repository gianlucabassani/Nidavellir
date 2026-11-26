// UX-16 browser check: the Forge shell. Every workspace page and an arena
// render inside the new shell in both themes; the sidebar foot stays visible
// while its menu scrolls; the logo goes home; the agents drawer and the
// attention dropdown open from live board data; search opens as a window at
// the top centre and moves by keyboard; nothing scrolls sideways at desktop
// or phone width. Runs against a mock stack with one seeded active arena.
// NV_UX16_CONFIG: {"arena"} (an active arena id).
const assert = require('node:assert/strict');
const fs = require('node:fs');
const {chromium} = require(process.env.NV_PLAYWRIGHT_MODULE || 'playwright');
const config = JSON.parse(fs.readFileSync(process.env.NV_UX16_CONFIG, 'utf8'));
const WEB = process.env.NV_WEB || 'http://127.0.0.1:15020';
const SHOTS = process.env.NV_UX16_SHOTS || '';

const PAGES = [
  '/console?workspace=research', '/console/research/new', '/console/arenas', '/console/board',
  '/console/activity?section=findings', '/console/activity?section=evidence',
  '/console/research/campaigns', '/console/research/review',
  '/console?workspace=benchmark', '/console/evaluations/new', '/console/evaluations',
  '/console/benchmark/registry', '/console/library/agents',
  '/console?workspace=range', '/console/arenas/new', '/console/library/targets', '/console/scenarios',
  '/console/profile', '/console/settings', '/console/activity?section=audit',
];

(async () => {
  const browser = await chromium.launch({headless: true,
    executablePath: process.env.NV_CHROMIUM_PATH || undefined, args: ['--no-sandbox']});
  const context = await browser.newContext({viewport: {width: 1440, height: 900}});
  const page = await context.newPage();
  const errors = []; page.on('pageerror', error => errors.push(String(error)));
  const checks = [];
  const shot = async name => SHOTS && page.screenshot({path: `${SHOTS}/${name}.png`});
  const overflow = () => page.evaluate(() => document.documentElement.scrollWidth > window.innerWidth + 1);
  const arena = `${WEB}/console/arena/${config.arena}`;
  try {
    await page.goto(`${WEB}/console?workspace=research`);
    await page.getByLabel('Username').fill(process.env.NV_USER || 'admin');
    await page.getByLabel('Password').fill(process.env.NV_PASSWORD || 'nidavellir');
    await page.getByRole('button', {name: 'Sign in'}).click();
    await page.locator('.topbar').waitFor();

    // Every sidebar destination renders in the shell, current item marked, no sideways scroll.
    for (const theme of ['day', 'night']) {
      await page.evaluate(t => localStorage.setItem('nidavellir-theme', t), theme);
      for (const path of PAGES) {
        await page.goto(WEB + path);
        await page.locator('.rail-foot').waitFor();
        await page.locator('#main h1').first().waitFor();
        assert.equal(await page.evaluate(() => document.documentElement.dataset.theme), theme);
        assert.equal(await overflow(), false, `${path} scrolls sideways (${theme})`);
        if (theme === 'day') await shot(`page${path.replace(/[/?=&]+/g, '_')}`);
      }
      checks.push(`${PAGES.length} pages render in the shell (${theme}), none scrolls sideways at 1440 px`);
    }
    await page.evaluate(() => localStorage.setItem('nidavellir-theme', 'day'));
    for (const [path, label] of [['/console/board', 'Agents board'], ['/console/evaluations/new', 'New comparison'],
      ['/console/scenarios', 'Scenarios'], ['/console/activity?section=evidence', 'Evidence']]) {
      await page.goto(WEB + path);
      const current = page.locator('.rail-nav [aria-current="page"]');
      assert.equal(await current.count(), 1, `${path}: one current sidebar item`);
      assert.match(await current.innerText(), new RegExp(label));
    }
    checks.push('the sidebar marks exactly one current item per page');

    // Planned items are visible, not links, and say why.
    await page.goto(`${WEB}/console?workspace=range`);
    const planned = page.locator('.rail-link.off', {hasText: 'Operations'});
    assert.equal(await planned.getAttribute('aria-disabled'), 'true');
    assert.equal(await planned.evaluate(el => el.tagName), 'SPAN');
    assert.match(await planned.getAttribute('title'), /Planned/);
    checks.push('Operations is shown as Planned with its reason, not as a link');

    // The logo returns home from anywhere.
    await page.goto(`${WEB}/console/benchmark/registry`);
    await page.locator('.brand').click();
    await page.waitForURL(/\/console\?workspace=research$/);
    assert.equal(await page.locator('.spaces a[aria-current="page"]').innerText(), 'Research');
    checks.push('the logo returns to the Research overview');

    // Arena: the sidebar becomes the arena menu; only its menu scrolls; the foot stays visible.
    await page.setViewportSize({width: 1440, height: 720});
    await page.goto(`${arena}?tab=forge`);
    await page.locator('#rail-arena nav[aria-label="Arena"]').waitFor();
    assert.equal(await page.locator('.arena-tool-list').count(), 0, 'old in-page tool list is gone');
    for (const name of ['Overview', 'Live', 'HTTP', 'Shell & logs', 'Findings', 'Target setup', 'Agent access'])
      await page.locator('#rail-arena .rail-link', {hasText: name}).first().waitFor();
    assert.equal(await page.locator('#rail-arena .rail-link[aria-current="page"]').innerText(), 'Overview');
    const rail = await page.evaluate(() => {
      const nav = document.querySelector('#rail-arena nav');
      nav.scrollTop = nav.scrollHeight;
      const foot = document.querySelector('.rail-foot').getBoundingClientRect();
      const ctx = document.querySelector('.rail-ctx').getBoundingClientRect();
      return {scrolls: nav.scrollHeight > nav.clientHeight, footBottom: Math.round(foot.bottom),
        footTop: foot.top, ctxTop: ctx.top, vh: window.innerHeight};
    });
    assert.equal(rail.scrolls, true, 'arena menu scrolls at 720 px');
    assert.equal(rail.footBottom, rail.vh, 'sidebar foot pinned to the bottom');
    assert.ok(rail.footTop < rail.vh - 40, 'sidebar foot visible');
    assert.ok(rail.ctxTop > 0, 'arena context stays at the top of the sidebar');
    await page.evaluate(() => window.scrollTo(0, document.body.scrollHeight));
    assert.equal(await page.locator('.rail-who').isVisible(), true);
    await shot('arena-720');
    checks.push('arena sidebar: context fixed on top, Tools/Record/Configure scroll, account and theme stay visible at 720 px');
    await page.locator('#rail-arena .rail-link', {hasText: 'HTTP'}).click();
    await page.waitForURL(/tab=http/);
    assert.equal(await page.locator('#rail-arena .rail-link[aria-current="page"]').innerText(), 'HTTP');
    checks.push('arena menu links switch the tool in place');
    await page.setViewportSize({width: 1440, height: 900});

    // Account menu and theme live at the sidebar foot.
    await page.locator('.rail-who').click();
    const menu = page.getByRole('menu');
    for (const item of ['Profile', 'Platform settings', 'Activity log', 'Log out'])
      await menu.getByRole('menuitem', {name: item}).waitFor();
    await page.keyboard.press('Escape');
    assert.equal(await menu.count(), 0);
    await page.getByRole('button', {name: 'Night theme'}).click();
    assert.equal(await page.evaluate(() => document.documentElement.dataset.theme), 'night');
    await page.reload();
    await page.locator('.rail-foot').waitFor();
    assert.equal(await page.evaluate(() => document.documentElement.dataset.theme), 'night');
    await shot('arena-night');
    await page.getByRole('button', {name: 'Day theme'}).click();
    checks.push('account menu (Profile, Settings, Activity log, Log out) and the theme switch sit at the sidebar foot; the theme persists');

    // Drawers open from live board data and close with Escape.
    await page.goto(`${WEB}/console?workspace=research`);
    await page.locator('.topbar button[title="Connected agents"]').click();
    const drawer = page.getByRole('dialog');
    await drawer.getByText(/Connected now/).waitFor();
    await drawer.locator('.drawer-body').waitFor();
    await page.waitForFunction(() => !document.querySelector('.drawer-body')?.textContent.includes('Loading'));
    await shot('drawer-agents');
    await page.keyboard.press('Escape');
    assert.equal(await drawer.count(), 0);
    checks.push('the agents drawer opens from the live board and closes with Escape');

    // Attention drops down from the bell, top right; dismissing updates the count.
    const bell = page.locator('.topbar button[aria-label^="Needs attention"]');
    await bell.click();
    const menu2 = page.getByRole('region', {name: 'Needs attention'});
    await menu2.waitFor();
    const geo = await page.evaluate(() => {
      const b = document.querySelector('.bell > button').getBoundingClientRect();
      const m = document.querySelector('.bell-menu').getBoundingClientRect();
      return {bellRight: b.right, menuRight: m.right, menuTop: m.top, bellBottom: b.bottom, vw: innerWidth};
    });
    assert.ok(Math.abs(geo.menuRight - geo.bellRight) < 2, 'dropdown aligned to the bell');
    assert.ok(geo.menuTop > geo.bellBottom && geo.menuTop < geo.bellBottom + 20, 'dropdown opens under the bell');
    assert.ok(geo.menuRight > geo.vw - 40, 'dropdown sits at the top right');
    await shot('attention-dropdown');
    const before = await menu2.locator('.bell-item').count();
    if (before > 0) {
      await menu2.locator('.bell-item .icon-button').first().click();
      await page.waitForFunction(n => document.querySelectorAll('.bell-item').length === n - 1, before);
      const label = await bell.getAttribute('aria-label');
      assert.equal(label, `Needs attention: ${before - 1}`);
    }
    await page.keyboard.press('Escape');
    assert.equal(await menu2.count(), 0);
    assert.equal(await page.evaluate(() => document.activeElement.closest('.bell') !== null), true, 'focus returns to the bell');
    await bell.click();
    await menu2.waitFor();
    await page.mouse.click(700, 500);
    assert.equal(await menu2.count(), 0, 'outside click closes the dropdown');
    checks.push(`attention drops down under the bell at the top right; dismissing updates the count (${before} → ${Math.max(0, before - 1)}); Escape and outside click close it`);

    // Search: a window at the top centre; recent pages when empty; keyboard moves.
    await page.goto(`${WEB}/console/scenarios`);
    await page.goto(`${WEB}/console?workspace=benchmark`);
    await page.locator('.topbar').waitFor();
    await page.keyboard.press('Control+k');
    const palette = page.getByRole('dialog', {name: 'Command palette'});
    await palette.waitFor();
    const box = await palette.boundingBox();
    const vw = page.viewportSize().width;
    assert.ok(Math.abs(box.x + box.width / 2 - vw / 2) < 2, 'search window is centred');
    assert.ok(box.y > 56 && box.y < 110, `search window opens just under the top bar (top ${Math.round(box.y)})`);
    await palette.locator('.palette-group', {hasText: 'Recent'}).waitFor();
    await palette.getByRole('option', {name: /Scenario library/}).waitFor();
    await shot('search-window');
    await page.keyboard.type('all eval');
    await palette.getByRole('option', {name: /All evaluations/}).waitFor();
    await page.keyboard.press('Enter');
    await page.waitForURL(/\/console\/evaluations$/);
    assert.equal(await palette.isVisible(), false);
    checks.push('Ctrl+K opens search as a centred window under the top bar, lists recent pages, and "all eval" + Enter jumps with 0 clicks');

    // Phone width: no sideways scroll; the sidebar is an overlay from the menu button.
    await page.setViewportSize({width: 390, height: 844});
    for (const path of ['/console?workspace=research', '/console/evaluations', `/console/arena/${config.arena}?tab=forge`]) {
      await page.goto(WEB + path);
      await page.locator('.topbar').waitFor();
      assert.equal(await overflow(), false, `${path} scrolls sideways at 390 px`);
    }
    await page.goto(`${WEB}/console?workspace=benchmark`);
    assert.equal(await page.locator('.rail').evaluate(el => el.getBoundingClientRect().right <= 0), true);
    await page.getByRole('button', {name: 'Open menu'}).click();
    await page.waitForFunction(() => document.querySelector('.rail').getBoundingClientRect().left >= 0);
    await shot('phone-menu');
    await page.locator('.rail-link', {hasText: 'Evaluations'}).click();
    await page.waitForURL(/\/console\/evaluations$/);
    await page.waitForFunction(() => document.querySelector('.rail').getBoundingClientRect().right <= 0);
    checks.push('at 390 px nothing scrolls sideways; the sidebar opens from the menu button and closes on navigation');

    assert.deepEqual(errors, []);
    console.log(JSON.stringify({ok: true, checks}, null, 2));
  } catch (error) {
    await shot('failure');
    console.log(JSON.stringify({ok: false, checks, errors, error: String(error.stack || error)}, null, 2));
    process.exitCode = 1;
  } finally {
    await browser.close();
  }
})();
