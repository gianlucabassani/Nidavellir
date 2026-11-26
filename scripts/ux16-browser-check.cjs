// UX-16 browser check: the Forge shell. Every workspace page and an arena
// render inside the new shell in both themes; the sidebar foot stays visible
// while its menu scrolls; the logo goes home; the agents and attention
// drawers open from live board data; nothing scrolls sideways at desktop or
// phone width. Runs against a mock stack with one seeded active arena.
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
    await page.locator('.topbar button[aria-label^="Needs attention"]').click();
    await page.getByRole('dialog').getByText('Needs attention').waitFor();
    await page.keyboard.press('Escape');
    checks.push('agents and attention drawers open from the live board and close with Escape');

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
