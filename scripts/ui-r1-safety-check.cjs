const { chromium } = require(process.env.NV_PLAYWRIGHT_MODULE || 'playwright');
const assert = require('node:assert/strict');
const fs = require('node:fs');
(async () => {
 const browser = await chromium.launch({headless:true, executablePath:process.env.NV_CHROMIUM_PATH || undefined, args:['--no-sandbox']});
 const report={date:new Date().toISOString(), base:process.env.NV_R1_WEB || 'http://127.0.0.1:15105', checks:[], audit:[]};
 try {
  const context=await browser.newContext(); const page=await context.newPage();
  await page.goto(report.base+'/console?workspace=research');
  assert.ok(page.url().includes('/login'));
  await page.fill('[name=username]','admin'); await page.fill('[name=password]',process.env.NV_R1_PASSWORD || process.env.NV_UI_R1_WEBUI_PASSWORD);
  await page.getByRole('button',{name:'Sign in'}).click(); await page.waitForURL('**/console?workspace=research');
  await page.locator('.research-grid').waitFor();
  report.checks.push('Unauthenticated deep link redirects to login; successful login restores Research');
  const csrf=await page.evaluate(async()=>{
    const r=await fetch('/api/console/arenas',{method:'POST',headers:{'Content-Type':'application/json','X-CSRFToken':'invalid'},body:JSON.stringify({scenario:'invalid',instance_id:'invalid'})});
    return {status:r.status,body:await r.text()};
  });
  assert.equal(csrf.status,400); assert.ok(/CSRF/i.test(csrf.body));
  report.checks.push('Real Flask CSRF denial:400 on authenticated POST with invalid token');
  // Sign the current fixture session with a timestamp older than Flask's
  // default 31-day maximum. Browser expiry alone would test cookie loss only.
  const {execFileSync}=require('node:child_process');
  const sessionCookie=(await context.cookies()).find(c=>c.name==='session');
  assert.ok(sessionCookie);
  const expired=execFileSync('docker',['compose','--env-file',process.env.NV_R1_ENV_FILE || '/tmp/nv-ui-r1.env','-f','docker-compose.ui-r1.yml','exec','-T','webui','python','-c',
    'import sys; from itsdangerous.timed import TimestampSigner; from webui.app import app; serializer=app.session_interface.get_signing_serializer(app); data=serializer.loads(sys.stdin.read()); TimestampSigner.get_timestamp=lambda self: 1; print(serializer.dumps(data))'],
    {input:sessionCookie.value,encoding:'utf8'}).trim();
  await context.addCookies([{...sessionCookie,value:expired}]);
  await page.getByRole('button',{name:/refresh/i}).first().click();
  await page.waitForURL('**/login?next=*');
  assert.ok(decodeURIComponent(page.url()).includes('/console?workspace=research'));
  report.checks.push('Expired signed session during mounted Research refresh redirects to login and retains next path');
  await page.fill('[name=username]','admin'); await page.fill('[name=password]',process.env.NV_R1_PASSWORD || process.env.NV_UI_R1_WEBUI_PASSWORD);
  await page.getByRole('button',{name:'Sign in'}).click(); await page.waitForURL('**/console?workspace=research');
  for (const path of ['/console?workspace=research','/console?workspace=benchmark','/console?workspace=range','/console/arenas','/console/evaluations','/console/research/new','/console/arenas/new','/console/arenas/custom','/console/activity']) {
   await page.goto(report.base+path); await page.waitForTimeout(500);
   const row=await page.evaluate(()=>({
    title:document.querySelector('h1')?.textContent,
    lang:document.documentElement.lang,
    unnamedButtons:[...document.querySelectorAll('button')].filter(e=>e.getBoundingClientRect().width && !(e.getAttribute('aria-label')||e.textContent||'').trim()).length,
    unlabeledInputs:[...document.querySelectorAll('input:not([type=hidden]),select,textarea')].filter(e=>e.getBoundingClientRect().width && !e.labels?.length && !e.hasAttribute('aria-label')&&!e.hasAttribute('aria-labelledby')).map(e=>({tag:e.tagName,type:e.type,name:e.name})),
    duplicateIds:[...document.querySelectorAll('[id]')].map(e=>e.id).filter((id,i,all)=>all.indexOf(id)!==i),
   }));
   row.path=path; row.reflow=[];
   for(const width of [320,390,1024,1440]){await page.setViewportSize({width,height:900});await page.waitForTimeout(50);row.reflow.push({width,overflow:await page.evaluate(()=>document.documentElement.scrollWidth-innerWidth)});}
   await page.keyboard.press('Tab'); row.keyboardFocus=await page.evaluate(()=>({tag:document.activeElement.tagName,name:document.activeElement.getAttribute('aria-label')||document.activeElement.textContent?.trim().slice(0,80)}));
   report.audit.push(row);
  }
  fs.writeFileSync(process.env.NV_R1_OUTPUT || '/tmp/nv-ui-r1-safety.json',JSON.stringify(report,null,2));
  console.log(JSON.stringify(report));
 } finally {await browser.close();}
})().catch(e=>{console.error(e);process.exitCode=1});
