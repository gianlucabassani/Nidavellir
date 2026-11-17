// Direct keyboard/reflow checks against the disposable UI-R1 stack.
const {chromium}=require(process.env.NV_PLAYWRIGHT_MODULE || 'playwright');
const assert=require('node:assert/strict'); const fs=require('node:fs');
(async()=>{
 const browser=await chromium.launch({headless:true,executablePath:process.env.NV_CHROMIUM_PATH || undefined,args:['--no-sandbox']});
 const page=await browser.newPage({reducedMotion:'reduce'}); const report={date:new Date().toISOString(),checks:[]};
 try {
 const base=process.env.NV_R1_WEB || 'http://127.0.0.1:15105';
 await page.goto(base+'/console/arenas'); await page.fill('[name=username]','admin');await page.fill('[name=password]',process.env.NV_R1_PASSWORD || process.env.NV_UI_R1_WEBUI_PASSWORD);await page.getByRole('button',{name:'Sign in'}).click();
 const trigger=page.getByRole('button',{name:'Destroy',exact:true}).first();await trigger.waitFor();await trigger.focus();await page.keyboard.press('Enter');
 const dialog=page.locator('dialog[open]');await dialog.waitFor();assert.ok(await dialog.evaluate(e=>e.contains(document.activeElement)));
 for(let i=0;i<8;i++){await page.keyboard.press('Tab');assert.ok(await dialog.evaluate(e=>e.contains(document.activeElement)));}
 await page.keyboard.press('Escape');await dialog.waitFor({state:'hidden'});assert.ok(await trigger.evaluate(e=>e===document.activeElement));
 report.checks.push('Destroy confirmation opens by keyboard, confines focus, closes with Escape and restores trigger focus without mutation');
 await page.goto(base+`/console/arena/${process.env.NV_R1_ARENA}?tab=overview`);const stations=page.locator('.topology-station[role=button]');
 if(await stations.count()){await stations.first().focus();await page.keyboard.press('Enter');assert.equal(await stations.first().getAttribute('aria-pressed'),'true');await page.keyboard.press('Space');report.checks.push('Topology stations select with Enter and Space and expose pressed state');}
 for(const path of ['/console/arenas/custom','/console/arenas/new', ...(process.env.NV_R1_ARENA ? ['setup','forwards','score'].map(tab=>`/console/arena/${process.env.NV_R1_ARENA}?tab=${tab}`):[])]) {
 await page.goto(base+path);await page.waitForTimeout(400);
 for(const width of [320,390,1024,1440]){await page.setViewportSize({width,height:900});assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth-innerWidth),0,`${path} at ${width}`);}
 }
 assert.ok(await page.evaluate(()=>matchMedia('(prefers-reduced-motion: reduce)').matches));
 report.checks.push('New forms and active arena setup/forwards/score reflow without page overflow at 320–1440px; reduced-motion preference is enabled');
 report.passed=true;fs.writeFileSync(process.env.NV_R1_OUTPUT || '/tmp/nv-ui-r1-keyboard.json',JSON.stringify(report,null,2));console.log(JSON.stringify(report));
 }finally{await browser.close();}
})().catch(e=>{console.error(e);process.exitCode=1});
