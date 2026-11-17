// Real-service UI-R3 journey. All credentials remain in the fixture's transaction store.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const {chromium} = require(process.env.NV_PLAYWRIGHT_MODULE || 'playwright');
const config = JSON.parse(fs.readFileSync(process.env.NV_R3_CONFIG, 'utf8'));
const WEB = 'http://127.0.0.1:15006';
(async () => {
 const browser = await chromium.launch({headless:true, executablePath:process.env.NV_CHROMIUM_PATH || undefined, args:['--no-sandbox']});
 const context = await browser.newContext(); const page = await context.newPage();
 const errors=[]; page.on('pageerror',error=>errors.push(String(error)));
 const sends=[]; page.on('request',request=>{if(request.method()==='POST' && request.url().endsWith('/replay')) sends.push(JSON.parse(request.postData()));});
 const report={date:new Date().toISOString(), checks:[], sends};
 try {
  await page.goto(WEB+`/console/arena/${config.arena}?tab=http`);
  await page.getByLabel('Username').fill('admin'); await page.getByLabel('Password').fill('nv06-local-only');
  await page.getByRole('button',{name:'Sign in'}).click();
  await page.getByRole('heading',{name:'Compare requests',exact:true}).waitFor();
  const groupName='Owned A versus foreign B';
  const groupButton=()=>page.locator('.http-saved-groups').getByRole('button',{name:new RegExp('^'+groupName)});
  if (!config.retained) {
   const row=page.locator('.http-transaction').filter({has:page.getByText(config.owned,{exact:true})});
   const originalSends=sends.length;
   await row.getByRole('button',{name:'Duplicate and edit',exact:true}).click();
   await page.locator('.http-replay-note').waitFor();
   await page.getByLabel('Path',{exact:true}).fill('/protected/B');
   await page.getByLabel('Request headers',{exact:true}).fill('X-Request-ID: r3foreign'+Date.now());
   assert.equal(sends.length,originalSends);
   assert.ok(!(await page.locator('.http-form').innerText()).includes('token-a-public'));
   await page.getByRole('button',{name:'Replay with edits ↗',exact:true}).click();
   await page.locator('.http-compared-responses').getByText('Captured bodies differ.',{exact:false}).waitFor();
   const denied=await page.getByLabel('Transaction B',{exact:true}).inputValue();
   assert.equal(await page.getByLabel('Transaction A',{exact:true}).inputValue(),config.owned);
   assert.match(await page.locator('[aria-label="Response B"]').innerText(),/Status 403/);
   await page.getByLabel('Group name',{exact:true}).fill(groupName);
   await page.getByLabel('A label',{exact:true}).fill('Owned object');
   await page.getByLabel('B label',{exact:true}).fill('Foreign object');
   await page.getByLabel('Research notes',{exact:true}).fill('Foreign access denied; owner control still needs independent review.');
   await page.getByRole('button',{name:'Save named comparison',exact:true}).click();
   await groupButton().waitFor();
   report.denied=denied;
   report.checks.push('Duplicating did not send; explicit object-change replay returned 403; named evidence pair saved');
   await row.getByRole('button',{name:'Duplicate and edit',exact:true}).click();
   await page.locator('.http-replay-note').waitFor();
   await page.getByLabel('Path',{exact:true}).fill('/protected/B');
   await page.getByLabel('Request headers',{exact:true}).fill('X-Request-ID: r3identity'+Date.now());
   await page.getByLabel('Credential source transaction (optional)',{exact:true}).fill(config.owner);
   await page.getByLabel('Credential header names',{exact:true}).fill('Authorization');
   await page.getByRole('button',{name:'Replay with edits ↗',exact:true}).click();
   await page.locator('[aria-label="Response B"]').getByText('Status 200',{exact:false}).waitFor();
   report.changed_account=await page.getByLabel('Transaction B',{exact:true}).inputValue();
   await page.getByLabel('Group name',{exact:true}).fill('Stored account B');
   await page.getByLabel('B label',{exact:true}).fill('Account B own object');
   await page.getByLabel('Research notes',{exact:true}).fill('Stored account B can read its own object; compare identity and body separately.');
   await page.getByRole('button',{name:'Save named comparison',exact:true}).click();
   await page.getByText('Named comparison saved.',{exact:false}).waitFor();
   assert.equal(sends.length,2);
   assert.ok(sends.every(body=>!JSON.stringify(body).includes('token-a-public') && !JSON.stringify(body).includes('token-b-operator')));
   report.checks.push('Stored account switch resolved credentials server-side; browser replay payloads contained no account tokens');
  }
  await page.reload(); await groupButton().click();
  await page.locator('[aria-label="Response B"]').getByText('Status 403',{exact:false}).waitFor();
  assert.match(await page.getByLabel('Research notes',{exact:true}).inputValue(),/owner control/);
  const findings=await page.locator('.http-compared-responses a').last().getAttribute('href');
  assert.ok(findings.includes('transaction=') && decodeURIComponent(findings).includes(','));
  const stored=await page.locator('.http-compared-responses a').evaluateAll(items=>items.slice(0,2).map(a=>a.href));
  for(const link of stored) assert.equal((await page.request.get(link)).status(),200);
  if(config.retained) assert.equal(await page.getByRole('button',{name:'Duplicate and edit',exact:true}).count(),0);
  for(const width of [320,390,1440]) {
   await page.setViewportSize({width,height:1000});
   assert.ok(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth+1),`overflow at ${width}`);
  }
  await page.evaluate(()=>window.scrollTo({top:0,behavior:'instant'}));
  await page.screenshot({path:config.output+'.png',fullPage:true});
  assert.deepEqual(errors,[]);
  assert.ok(!(await page.locator('.http-comparison-panel').innerText()).includes('token-b-operator'));
  report.checks.push('Saved labels/notes/evidence restored after reload; both finding refs linked; retained transactions readable; responsive widths passed');
  report.errors=errors;
  fs.writeFileSync(config.output,JSON.stringify(report,null,2),{flag:'wx'});
 } catch(error) {await page.screenshot({path:config.output+'.failure.png',fullPage:true});throw error;}
 finally {await browser.close();}
})().catch(error=>{console.error(error);process.exit(1)});
