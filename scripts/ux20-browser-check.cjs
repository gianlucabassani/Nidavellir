// UX-20 browser check: the Copilot panel against a stub OpenAI-compatible
// model (NV_UX20_MODEL_URL, e.g. http://nv-ux-fakellm:9100/v1 on the stack
// network). The stub plans an arena summary and the agents board, answers with
// **bold**, a console link and a list, and appends a proposal when asked to
// extend or stop. NV_UX20_CONFIG: {"arena"} (an active arena id).
const assert = require('node:assert/strict');
const fs = require('node:fs');
const {chromium} = require(process.env.NV_PLAYWRIGHT_MODULE || 'playwright');
const config = JSON.parse(fs.readFileSync(process.env.NV_UX20_CONFIG, 'utf8'));
const WEB = process.env.NV_WEB || 'http://127.0.0.1:15020';
const MODEL_URL = process.env.NV_UX20_MODEL_URL || 'http://nv-ux-fakellm:9100/v1';
const SHOTS = process.env.NV_UX20_SHOTS || '';

(async () => {
  const browser = await chromium.launch({headless: true,
    executablePath: process.env.NV_CHROMIUM_PATH || undefined, args: ['--no-sandbox']});
  const page = await (await browser.newContext({viewport: {width: 1440, height: 1000}})).newPage();
  const errors = []; page.on('pageerror', error => errors.push(String(error)));
  const checks = [];
  const shot = async name => SHOTS && page.screenshot({path: `${SHOTS}/${name}.png`});
  const panel = page.getByRole('complementary', {name: 'Copilot'});
  const send = async text => {
    await panel.getByRole('textbox', {name: 'Message', exact: true}).fill(text);
    await panel.getByRole('textbox', {name: 'Message', exact: true}).press('Enter');
    await panel.locator('.cl-a .cp-rich').last().waitFor();
    await page.waitForFunction(() => !document.querySelector('.cp-send.stop'));
  };
  try {
    await page.goto(`${WEB}/console/arena/${config.arena}?tab=forge`);
    await page.getByLabel('Username').fill(process.env.NV_USER || 'admin');
    await page.getByLabel('Password').fill(process.env.NV_PASSWORD || 'nidavellir');
    await page.getByRole('button', {name: 'Sign in'}).click();
    await page.locator('.dash').waitFor();

    // Launcher sits in the top bar; the panel opens docked under it.
    await page.locator('.topbar').getByRole('button', {name: 'Copilot'}).click();
    await panel.waitFor();
    const box = await panel.boundingBox();
    assert.ok(box.y > 56 && box.x + box.width > 1400, 'docked at the right under the top bar');

    // Connect the stub model from the panel.
    await panel.getByRole('button', {name: 'Model connection'}).click();
    await panel.getByLabel('Provider').selectOption('custom');
    await panel.getByRole('textbox', {name: 'Model'}).fill('stub-model');
    await panel.getByLabel('API key').fill('stub-key');
    await panel.getByLabel('Endpoint URL').fill(MODEL_URL);
    await panel.getByRole('button', {name: 'Save connection'}).click();
    await panel.getByText('What do you want to know?').waitFor();
    assert.match(await panel.locator('.cp-tt small').innerText(), /stub-model/);
    await shot('copilot-empty');
    checks.push('the panel opens under the top bar and connects a model from its own form');

    // A turn with the page as context: lookups as chips, rich but restricted text.
    await panel.getByRole('button', {name: 'Add this page as context'}).click();
    await panel.locator('.chip.on').waitFor();
    await send('How is this arena going?');
    const chips = await panel.locator('.look').allInnerTexts();
    assert.deepEqual(chips.map(c => c.trim()), ['Looked up arena summary', 'Looked up agents board']);
    const answer = panel.locator('.cl-a .cp-rich').last();
    assert.equal(await answer.locator('b').first().innerText(), 'Juice');
    assert.equal(await answer.locator('a').getAttribute('href'), `/console/arena/${config.arena}`);
    assert.equal(await answer.locator('.cp-li').count(), 2);
    assert.match(await panel.locator('.cl-u .cp-sent-page').innerText(), /with page: Arena/);
    checks.push('a turn shows lookup chips, then restricted rich text (bold, an in-console link, a list); the page went as context');

    // A proposal: Apply runs the console's own endpoint, then records the result.
    await send('Please extend this arena');
    const card = panel.locator('.cp-prop').last();
    await card.getByText(`Extend ${config.arena} by 30 minutes`).waitFor();
    assert.equal(await panel.locator('.cp-rich').last().innerText().then(t => t.includes('nv-proposal')), false);
    await shot('copilot-proposal');
    const extend = page.waitForResponse(r => r.url().endsWith(`/api/console/arenas/${config.arena}/extend`));
    await card.getByRole('button', {name: 'Apply'}).click();
    assert.equal((await extend).status(), 200);
    await card.getByText(/^Applied at /).waitFor();
    checks.push('a proposal card shows the change (not the raw block); Apply calls the console extend endpoint and the card records it');

    // Deny leaves things unchanged.
    await send('Stop research here');
    const stop = panel.locator('.cp-prop').last();
    await stop.getByRole('button', {name: 'Deny'}).click();
    await stop.getByText('Nothing was changed.').waitFor();
    checks.push('Deny closes a proposal without calling anything');

    // History keeps the chat across navigation and reloads.
    await page.goto(`${WEB}/console?workspace=benchmark`);
    await page.locator('.topbar').getByRole('button', {name: 'Copilot'}).click();
    await panel.getByRole('button', {name: 'Chats'}).click();
    const row = panel.locator('.cp-hist li').filter({hasText: 'How is this arena going?'}).first(); // newest first
    await row.waitFor();
    await row.locator('button').first().click();
    await panel.locator('.cp-prop.applied').waitFor();
    await panel.locator('.cp-prop.denied').waitFor();
    assert.equal(await panel.locator('.look').count(), 6);
    await panel.locator('.cp-planned').count().then(n => assert.equal(n, 0));
    checks.push('history reopens the chat after navigating: messages, lookups and both proposal outcomes are stored');

    // Agent inbox is visible as Planned; Escape closes and returns focus.
    await panel.getByRole('button', {name: 'Chats'}).click();
    await panel.locator('.cp-planned .feature-tag').getByText('Planned').waitFor();
    await page.keyboard.press('Escape');
    assert.equal(await panel.count(), 0);
    checks.push('the agent inbox shows as Planned; Escape closes the panel');

    // Phone width: full-width panel, nothing scrolls sideways.
    await page.setViewportSize({width: 390, height: 844});
    await page.locator('.topbar').getByRole('button', {name: 'Copilot'}).click();
    await panel.waitFor();
    assert.equal(await page.evaluate(() => document.documentElement.scrollWidth > window.innerWidth + 1), false);
    checks.push('at 390 px the panel is full width without sideways scroll');

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
