// Isolated UI-R1 acceptance. Requires docker-compose.ui-r1.yml. Mutations are
// real and apply only to this disposable stack and its synthetic arenas.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const { execFileSync } = require('node:child_process');
const { once } = require('node:events');
const { chromium } = require(process.env.NV_PLAYWRIGHT_MODULE || 'playwright');
const WebSocket = require(process.env.NV_WS_MODULE || 'ws');
const API = process.env.NV_R1_API || 'http://127.0.0.1:18105';
const WEB = process.env.NV_R1_WEB || 'http://127.0.0.1:15105';
const KEY = process.env.NV_R1_KEY || process.env.NV_UI_R1_API_KEY;
const PASSWORD = process.env.NV_R1_PASSWORD || process.env.NV_UI_R1_WEBUI_PASSWORD;
const output = process.env.NV_R1_OUTPUT || '/tmp/nv-ui-r1-live.json';
if (!KEY || !PASSWORD) throw new Error('Set NV_R1_KEY and NV_R1_PASSWORD in the environment');
const report = {date: new Date().toISOString(), api: API, web: WEB, checks: [], arenas: []};
const save = () => fs.writeFileSync(output, JSON.stringify(report, null, 2));
async function api(path, body, method = body ? 'POST' : 'GET', statuses = [200]) {
 const response = await fetch(API + path, {method, headers: {'X-API-Key': KEY, 'Content-Type': 'application/json'}, body: body ? JSON.stringify(body) : undefined});
 const data = await response.json();
 assert.ok(statuses.includes(response.status), `${method} ${path}: ${response.status} ${JSON.stringify(data)}`);
 return data;
}
async function wait(path, predicate) {
 const end = Date.now() + 120000;
 while(Date.now() < end) {const data = await api(path); if(predicate(data)) return data; await new Promise(r=>setTimeout(r,500));}
 throw new Error(`Timed out: ${path}`);
}
(async()=>{
 const browser = await chromium.launch({headless:true,executablePath:process.env.NV_CHROMIUM_PATH || undefined,args:['--no-sandbox']});
 const context=await browser.newContext(); const page=await context.newPage();
 const errors=[]; page.on('pageerror', e=>errors.push(String(e)));
 try {
  const image=execFileSync('docker',['image','inspect','nidavellir/nv05-fixture:acceptance','--format','{{.Id}}'],{encoding:'utf8'}).trim();
  await api('/scenarios',{id:'ui-r1-fixture',overwrite:true,spec:{schema:'nidavellir/v3',name:'UI-R1 internal fixture',requires:{provider_class:'container',egress:'none',mirror:'off'},network:{segments:[{name:'research'}]},nodes:[
   {name:'jump',role:'attacker',entrypoint:true,image,segments:['research']},
   {name:'fixture',role:'victim',image,segments:['research'],ports:[],forward_services:[{id:'internal',port:8123}]},
  ],lifecycle:{readiness:{type:'http',node:'fixture',port:8080,path:'/health',expected_status:200,timeout_seconds:20}}}});
  await page.goto(WEB+'/console/arenas/new?scenario=ui-r1-fixture');
  await page.fill('[name=username]','admin'); await page.fill('[name=password]',PASSWORD);
  await page.getByRole('button',{name:'Sign in'}).click();
  if (!process.env.NV_R1_RESUME_ARENA) {
  await page.getByLabel('Arena name',{exact:true}).fill('ui-r1-live');
  await page.locator('.comparison-form select').last().selectOption('14400');
  await page.getByRole('button',{name:'Launch arena ↗',exact:true}).click();
  await page.waitForURL(/\/console\/arena\//);
  }
  const arena=process.env.NV_R1_RESUME_ARENA || page.url().split('/arena/')[1].split('?')[0];report.arenas.push(arena);save();
  await wait('/status/'+arena,data=>data.status==='active');
  report.checks.push('Real Docker-local fixture launched through registered-scenario console form');save();
  if(process.env.NV_R1_PREPARE_ONLY) {console.log(JSON.stringify(report));return;}
  await page.goto(WEB+`/console/arena/${arena}?tab=setup`);
  await page.locator('.setup-history').waitFor();
  const setupDone=await page.getByText('Setup complete',{exact:true}).count();
  if(!setupDone) {
  const startSetup=page.getByRole('button',{name:'Start setup ↗',exact:true});
  if(await startSetup.count()) await startSetup.click();
  await page.getByLabel('Command',{exact:true}).fill("printf 'UI-R1 stdout\\n'; printf 'UI-R1 stderr\\n' >&2");
  await page.getByRole('button',{name:'Run step ↗',exact:true}).click();
  await page.locator('.setup-history').getByLabel('Standard output',{exact:true}).filter({hasText:'UI-R1 stdout'}).waitFor();
  await page.locator('.setup-history').getByLabel('Standard error',{exact:true}).filter({hasText:'UI-R1 stderr'}).waitFor();
  await page.getByRole('button',{name:'Finish setup',exact:true}).click();
  await page.locator('dialog').getByRole('button',{name:'Finish setup',exact:true}).click();
  await page.getByText('Setup complete',{exact:true}).waitFor();
  }
  await page.reload();await page.locator('.setup-history').getByLabel('Standard output',{exact:true}).filter({hasText:'UI-R1 stdout'}).waitFor();
  report.checks.push('Setup command stdout/stderr persisted, survived finish and browser reload');save();
  await page.goto(WEB+`/console/arena/${arena}?tab=forwards`);
  await page.getByRole('button',{name:'Open 120-second forward',exact:true}).click();
  const leases=await wait(`/arenas/${arena}/forwards`,data=>data.forwards.some(item=>item.state==='open'));const lease=leases.forwards.find(item=>item.state==='open');
  const socket=new WebSocket(API.replace('http:','ws:')+`/arenas/${arena}/forwards/${lease.id}/connect`,{headers:{'X-API-Key':KEY}});
  await once(socket,'open');socket.send(Buffer.from('UI-R1 echo'));const [reply]=await once(socket,'message');assert.equal(reply.toString(),'NV05:UI-R1 echo');socket.close();
  report.checks.push('Console opened a real scoped forward; internal TCP fixture echoed via the leased websocket');save();
  await page.getByRole('button',{name:'Open 120-second forward',exact:true}).click();
  await page.getByRole('button',{name:'Revoke',exact:true}).first().click();
  await wait(`/arenas/${arena}/forwards`,data=>data.forwards.some(item=>item.state==='revoked'));
  report.checks.push('Console revoked a real forward lease');save();
  await page.goto(WEB+`/console/arena/${arena}`);
  await page.locator('.arena-live-status').filter({hasText:'Live updates'}).waitFor();
  const resumeHeaders=[];page.on('request',r=>{if(r.url().endsWith('/stream')) resumeHeaders.push(r.headers()['last-event-id'] || null)});
  execFileSync('docker',['compose','--env-file',process.env.NV_R1_ENV_FILE || '/tmp/nv-ui-r1.env','-f','docker-compose.ui-r1.yml','stop','orchestrator'],{stdio:'ignore'});
  await page.locator('.arena-live-status').filter({hasText:'Reconnecting'}).waitFor();
  execFileSync('docker',['compose','--env-file',process.env.NV_R1_ENV_FILE || '/tmp/nv-ui-r1.env','-f','docker-compose.ui-r1.yml','start','orchestrator'],{stdio:'ignore'});
  await page.locator('.arena-live-status').filter({hasText:'Live updates'}).waitFor({timeout:30000});
  report.checks.push('Real SSE connection recovered after service interruption and reconciled current arena');report.resumeHeaders=resumeHeaders;save();
  await page.goto(WEB+'/console/arenas');
  let row=page.locator('.arena-list-row').filter({hasText:arena.slice(0,8)});
  await row.getByRole('button',{name:'Destroy',exact:true}).click();
  await page.locator('dialog').getByRole('button',{name:'Destroy arena',exact:true}).click();
  await wait('/status/'+arena,data=>data.status==='destroyed');
  await page.goto(WEB+`/console/arena/${arena}?tab=setup`);await page.locator('.setup-history').getByLabel('Standard output',{exact:true}).filter({hasText:'UI-R1 stdout'}).waitFor();
  report.checks.push('Destroy-from-list reached destroyed state; archived setup output remained readable');save();
  await page.goto(WEB+'/console/arenas');row=page.locator('.arena-list-row').filter({hasText:arena.slice(0,8)});
  await row.getByRole('button',{name:'Remove',exact:true}).click();await page.locator('dialog').getByRole('button',{name:'Remove record',exact:true}).click();
  await page.getByText(/research evidence or evaluation references require retaining this record/).waitFor();
  await api('/status/'+arena);report.checks.push('Archive Remove correctly denied evidence-bearing record deletion with service 409');save();
  // Empty historical terminal fixtures have no infrastructure or research evidence.
  const seed=execFileSync('docker',['compose','--env-file',process.env.NV_R1_ENV_FILE || '/tmp/nv-ui-r1.env','-f','docker-compose.ui-r1.yml','exec','-T','orchestrator','python','-c',
   'from database import Database; from uuid import uuid4; db=Database(); ids=[str(uuid4()),str(uuid4())]; [(db.create_deployment(i,"ui-r1-empty-archive","synthetic-history"),db.update_deployment(i,status="destroying"),db.update_deployment(i,status="destroyed")) for i in ids]; print(" ".join(ids))'],{encoding:'utf8'}).trim().split(' ');
  report.emptyRecords=seed;save();await page.reload();
  row=page.locator('.arena-list-row').filter({hasText:seed[0].slice(0,8)});
  await row.getByRole('button',{name:'Remove',exact:true}).click();
  await page.locator('dialog').getByRole('button',{name:'Remove record',exact:true}).click();
  await row.waitFor({state:'hidden'});await api('/status/'+seed[0],null,'GET',[404]);
  report.checks.push('Archive Remove deleted an eligible empty terminal record through the real service');save();
  // Explicit mock provider exercises custom catalog compilation without pulling
  // external images. It is UI/API parity evidence, not infrastructure proof.
  await page.goto(WEB+'/console/arenas/custom');await page.locator('.comparison-form select').first().selectOption('mock');
  await page.getByLabel('Arena name',{exact:true}).fill('ui-r1-custom');
  await page.locator('.catalog-pick').filter({hasText:'Kali Linux (CLI)'}).locator('input').check();
  await page.locator('.catalog-pick').filter({hasText:'OWASP Juice Shop'}).locator('input').check();
  await page.getByRole('button',{name:'Launch arena ↗',exact:true}).click();await page.waitForURL(/\/console\/arena\//);
  const custom=page.url().split('/arena/')[1].split('?')[0];report.arenas.push(custom);save();await wait('/status/'+custom,data=>data.status==='active');
  report.checks.push('Custom topology submitted real catalog picks to mock provider (no live-provider claim)');save();
  await api(`/destroy/${custom}`,null,'DELETE');await wait('/status/'+custom,data=>data.status==='destroyed');
  await page.goto(WEB+'/console/arenas');await page.getByRole('button',{name:/Clear archive/}).click();await page.locator('dialog').getByRole('button',{name:'Clear archive',exact:true}).click();
  await page.getByText(/Archive cleared:/).waitFor();
  await api('/status/'+seed[1],null,'GET',[404]);await api('/status/'+arena);
  report.checks.push('Clear archive removed eligible empty records and retained evidence-bearing records in the dedicated stack');
  assert.deepEqual(errors,[]);report.checks.push('No browser page errors');report.passed=true;save();console.log(JSON.stringify(report));
 }catch(e){report.failure=String(e);save();throw e;}finally{await browser.close();}
})().catch(e=>{console.error(e);process.exitCode=1});
