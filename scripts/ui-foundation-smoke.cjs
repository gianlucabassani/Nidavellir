// Forge foundations acceptance (C1). Read-only: page loads, focus and theme toggles only.
// Usage: NV_PLAYWRIGHT_MODULE=… NV_CHROMIUM_PATH=… node scripts/ui-foundation-smoke.cjs
const { chromium } = require(process.env.NV_PLAYWRIGHT_MODULE || 'playwright');
const path = require('path');
const fs = require('fs');

const baseURL = process.env.NV_UI_URL || 'http://127.0.0.1:5000';
const arenaId = process.env.NV_UI_ARENA_ID || '7b2b268a-1a09-4cc3-aa71-f733e73450bc';
const renderDir = process.env.NV_RENDER_DIR || '';
const pages = {
  research: '/console?workspace=research',
  benchmark: '/console?workspace=benchmark',
  range: '/console?workspace=range',
  arena: `/console/arena/${encodeURIComponent(arenaId)}?tab=forge`,
};
const widths = [1440, 1024, 390, 320];
const failures = [];
let checks = 0;
function check(label, ok, detail = '') {
  checks++;
  if (!ok) failures.push(`${label}${detail ? `: ${detail}` : ''}`);
}

// Runs in the page: WCAG relative luminance and contrast of computed colours.
const colourHelpers = `
  window.__nvLum = (value) => {
    const m = value.match(/rgba?\\(([^)]+)\\)/);
    if (!m) return null;
    const [r, g, b] = m[1].split(',').slice(0, 3).map((v) => {
      const c = Number(v) / 255;
      return c <= 0.03928 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4;
    });
    return 0.2126 * r + 0.7152 * g + 0.0722 * b;
  };
  window.__nvContrast = (fg, bg) => {
    const probe = document.createElement('span');
    probe.style.color = 'var(' + fg + ')';
    probe.style.backgroundColor = 'var(' + bg + ')';
    document.body.append(probe);
    const s = getComputedStyle(probe);
    const a = window.__nvLum(s.color), b = window.__nvLum(s.backgroundColor);
    probe.remove();
    if (a === null || b === null || !getComputedStyle(document.documentElement).getPropertyValue(fg).trim()) return 0;
    return (Math.max(a, b) + 0.05) / (Math.min(a, b) + 0.05);
  };
`;

(async () => {
  const browser = await chromium.launch({
    headless: true,
    executablePath: process.env.NV_CHROMIUM_PATH || undefined,
    args: ['--no-sandbox'],
  });
  for (const theme of ['day', 'night']) {
    for (const reducedMotion of theme === 'day' ? ['no-preference', 'reduce'] : ['no-preference']) {
      const context = await browser.newContext({ viewport: { width: 1440, height: 1000 }, reducedMotion });
      await context.addInitScript((t) => {
        try { localStorage.setItem('nidavellir-theme', t); } catch { /* storage unavailable */ }
      }, theme);
      await context.addInitScript(colourHelpers);
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
      if (reducedMotion === 'reduce') {
        await page.goto(baseURL + pages.arena);
        await page.locator('.forge-workbench').waitFor();
        const animation = await page.evaluate(() => getComputedStyle(document.querySelector('.forge-workbench')).animationName);
        check('reduced motion disables forge animation', animation === 'none', animation);
        await context.close();
        continue;
      }
      for (const [name, url] of Object.entries(pages)) {
        for (const width of widths) {
          await page.setViewportSize({ width, height: width < 760 ? 844 : 1000 });
          await page.goto(baseURL + url);
          await page.locator('main h1').first().waitFor();
          await page.waitForTimeout(250);
          const tag = `${name}/${theme}/${width}`;
          const m = await page.evaluate(() => {
            const bar = document.querySelector('.command-bar')?.getBoundingClientRect();
            const tabbar = document.querySelector('.workspace-tabbar');
            const tabVisible = !!tabbar && getComputedStyle(tabbar).display !== 'none' && tabbar.getBoundingClientRect().height > 0;
            const tabLabels = tabbar ? [...tabbar.querySelectorAll('a')].map((a) => a.textContent.replace(/[ᚠ-ᛸ]/g, '').trim()) : [];
            const numbered = [];
            const walker = document.createTreeWalker(document.querySelector('main'), NodeFilter.SHOW_TEXT);
            while (walker.nextNode()) {
              const text = walker.currentNode.textContent.trim();
              const el = walker.currentNode.parentElement;
              if (/^\d{2} \/ /.test(text) && el && el.getClientRects().length && getComputedStyle(el).visibility !== 'hidden') numbered.push(text);
            }
            const forge = document.querySelector('.forge-workbench');
            return {
              font: getComputedStyle(document.body).fontFamily,
              overflow: document.documentElement.scrollWidth > innerWidth,
              barHeight: bar ? bar.height : 0,
              barWidth: bar ? bar.width : 0,
              tabVisible,
              tabLabels,
              numbered,
              forgeLum: forge ? window.__nvLum(getComputedStyle(forge).backgroundColor) : null,
              brass: window.__nvContrast('--nv-brass', '--nv-surface'),
              muted: window.__nvContrast('--nv-muted', '--nv-surface'),
            };
          });
          check(`${tag} Geist font`, /^"?Geist/.test(m.font), m.font);
          check(`${tag} no horizontal overflow`, !m.overflow);
          if (width >= 1024) {
            check(`${tag} nav height <= 58`, m.barHeight > 0 && m.barHeight <= 58, String(m.barHeight));
            check(`${tag} nav width <= 1120`, m.barWidth > 0 && m.barWidth <= 1120, String(m.barWidth));
          }
          if (width < 760) {
            check(`${tag} phone tab bar visible`, m.tabVisible);
            check(`${tag} phone tab labels`, m.tabLabels.join('|') === 'Research|Benchmark|Cyber Range', m.tabLabels.join('|'));
          }
          check(`${tag} no numbered section labels`, m.numbered.length === 0, m.numbered.slice(0, 3).join(', '));
          if (name === 'arena' && m.forgeLum !== null) {
            check(`${tag} forge theme lock`, theme === 'day' ? m.forgeLum > 0.6 : m.forgeLum < 0.1, String(m.forgeLum));
          }
          if (width === 1440 && name === 'research') {
            check(`${tag} brass contrast >= 4.5`, m.brass >= 4.5, m.brass.toFixed(2));
            check(`${tag} muted contrast >= 4.5`, m.muted >= 4.5, m.muted.toFixed(2));
            await page.keyboard.press('Tab');
            await page.keyboard.press('Tab');
            const ring = await page.evaluate(() => {
              const el = document.activeElement;
              return { inNav: !!el?.closest('.site-header'), outline: el ? getComputedStyle(el).outlineStyle : 'none' };
            });
            check(`${tag} keyboard focus ring in nav`, ring.inNav && ring.outline !== 'none', JSON.stringify(ring));
          }
          if (renderDir && [1440, 390].includes(width)) {
            fs.mkdirSync(renderDir, { recursive: true });
            await page.screenshot({ path: path.join(renderDir, `foundation-${name}-${theme}-${width}.png`), fullPage: width >= 760 });
          }
        }
      }
      check(`${theme} no page errors`, errors.length === 0, errors.join('; '));
      await context.close();
    }
  }
  await browser.close();
  if (failures.length) {
    console.log(`FAIL ${failures.length}/${checks}`);
    for (const failure of failures) console.log(' - ' + failure);
    process.exit(1);
  }
  console.log(`PASS ${checks}/${checks} foundation checks`);
})().catch((error) => {
  console.error(error);
  process.exit(1);
});
