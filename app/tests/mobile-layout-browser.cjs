'use strict';
// Browser plugin not available. Real Edge, local HTTP and an isolated encrypted store.
const {chromium}=require('C:/Users/hp/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules/playwright');
const assert=require('node:assert/strict'),fs=require('node:fs'),path=require('node:path'),os=require('node:os'),{spawn}=require('node:child_process');
const root=path.resolve(__dirname,'../..'),data=fs.mkdtempSync(path.join(os.tmpdir(),'shansuan-layout-data-'));
const output=path.join(os.tmpdir(),'shansuan-layout-evidence'),url='http://127.0.0.1:18883';
fs.mkdirSync(output,{recursive:true});
let server,browser,page;const checks=[],errors=[],requests=[];
async function check(name,fn){await fn();checks.push(name);console.log('PASS '+name)}
(async()=>{try{
 server=spawn(path.join(root,'.venv/Scripts/python.exe'),['app/scripts/run.py','--data-dir',data,'--port','18883','--no-browser','--no-model'],{cwd:root,windowsHide:true,env:{...process.env,PYTHONUTF8:'1'},stdio:'ignore'});
 for(let i=0;i<100;i++){try{if((await fetch(url+'/api/session')).ok)break}catch{}await new Promise(r=>setTimeout(r,150))}
 browser=await chromium.launch({channel:'msedge',headless:true});
 const context=await browser.newContext({viewport:{width:390,height:844},colorScheme:'light'});page=await context.newPage();
 page.on('pageerror',e=>errors.push(e.message));page.on('request',r=>requests.push(r.url()));
 await page.goto(url);
 async function call(route,method='GET',body){return page.evaluate(async({route,method,body})=>{const s=await fetch('/api/session').then(r=>r.json());const r=await fetch('/api'+route,{method,headers:{'Content-Type':'application/json','X-CSRF-Token':s.csrf},body:body===undefined?undefined:JSON.stringify(body)});const v=await r.json();if(!r.ok)throw Error(v.error.message);return v},{route,method,body})}
 const day=await page.evaluate(()=>new Date().toLocaleDateString('en-CA'));
 await call('/profile','PUT',{sex:'女',age:30,height:165,weight:60,sleep_hours:7,exercise_weekly:2,activity:'轻度',lifestyle:'上班族',goals:['补充蛋白质'],primary_goal:'补充蛋白质',health_status:'明确无',allergy_status:'明确无'});
 const open=async route=>{await page.goto(url+route);await page.locator('h1').first().waitFor();await page.locator('.card,.weather-card').first().waitFor()};
 const snapshot=()=>Promise.all(['/profile','/records?date='+day,'/feedback/'+day,'/plans/'+day,'/products'].map(r=>call(r)));
 await open('/');
 await check('mobile primary navigation exists and reaches five original routes',async()=>{
  assert.equal(await page.locator('.mobile-primary-nav').count(),1,'missing mobile bottom navigation');
  const nav=page.getByRole('navigation',{name:'主导航'});
  assert.deepEqual(await nav.locator('a').evaluateAll(a=>a.map(x=>[x.getAttribute('href'),x.textContent])),[['/','今日'],['/meals','饮食'],['/records','记录'],['/report','报告'],['/profile','我的']]);
  for(const [route,label] of [['/meals','饮食'],['/records','记录'],['/report','报告'],['/profile','我的'],['/','今日']]){
   await nav.getByRole('link',{name:label,exact:true}).click();await page.waitForURL(url+route);await nav.locator('a[href="'+route+'"][aria-current=page]').waitFor();
   assert.equal(await nav.getByRole('link',{name:label,exact:true}).getAttribute('aria-current'),'page');
  }
 });
 await check('shortcut entry points and real water operation preserve original flows',async()=>{
  const quick=page.getByRole('navigation',{name:'快捷操作'});
  await quick.getByRole('link',{name:'拍照分析',exact:true}).click();await page.getByLabel('选择照片（JPG / PNG / WebP，最多12MB）').waitFor();
  await open('/');await quick.getByRole('link',{name:'问问助手',exact:true}).click();await page.getByLabel('你的问题',{exact:true}).waitFor();
  await open('/');await quick.getByRole('link',{name:'记录饮食',exact:true}).click();await page.getByRole('button',{name:'＋ 记一餐',exact:true}).waitFor();
  await open('/');const count=(await call('/records?date='+day)).record_count;
  await quick.getByRole('button',{name:'记录饮水，添加200ml'}).click();await page.getByTestId('home-water').getByRole('status').waitFor();
  assert.equal((await call('/records?date='+day)).life.water_ml,200);assert.equal((await call('/records?date='+day)).record_count,count);
 });
 await check('mobile menu retains secondary routes, appearance and private save',async()=>{
  for(const route of ['/photo','/chat','/feedback','/products']){
   await open('/records');await page.getByRole('button',{name:'更多功能',exact:true}).click();
   const menu=page.getByRole('dialog');assert(await menu.getByRole('button',{name:'手动保存',exact:true}).isVisible());
   assert.equal(await menu.getByRole('button',{name:/使用.*外观/}).count(),3);
   await menu.locator('nav a[href="'+route+'"]').click();await page.waitForURL(url+route);
  }
 });
 await check('themes and all routes retain data, avoid overflow and preserve desktop navigation',async()=>{
  await open('/');const before=await snapshot();const writeStart=requests.length;
  for(const theme of ['light','dark']){
   await page.evaluate(theme=>{localStorage.setItem('shansuan.appearance',theme)},theme);
   for(const width of [390,320,1280]){
    await page.setViewportSize({width,height:844});
    for(const route of ['/','/meals','/records','/report','/profile','/photo','/chat','/feedback','/products']){
     await open(route);await page.waitForTimeout(260);
     assert.equal(await page.locator('html').getAttribute('data-theme'),theme);
     assert(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth+1),`overflow ${theme} ${width} ${route}`);
     const nav=page.getByRole('navigation',{name:'主导航'});
     if(width<600){assert(await nav.isVisible());assert.equal(await page.locator('.layout>aside').isVisible(),false);if(route==='/')assert.equal(await page.locator('.home-products-link').isVisible(),false);
      await page.evaluate(()=>scrollTo(0,document.body.scrollHeight));
      const overlap=await page.evaluate(()=>{const nav=document.querySelector('.mobile-primary-nav').getBoundingClientRect();const root=document.querySelector('.page')||document.querySelector('.home-content');return [...root.querySelectorAll('button,input,textarea,a')].filter(e=>e.getClientRects().length).some(e=>{const b=e.getBoundingClientRect();return b.bottom>nav.top&&b.top<nav.bottom&&b.bottom>0&&b.top<innerHeight})});
      assert.equal(overlap,false,`bottom navigation covers content ${width} ${route}`);
     }else{assert.equal(await nav.isVisible(),false);if(route!=='/')assert(await page.locator('.layout>aside').isVisible())}
     if(width!==320&&['/','/meals','/feedback','/photo'].includes(route)){await page.evaluate(()=>scrollTo(0,0));await page.screenshot({path:path.join(output,`${route.slice(1)||'home'}-${theme}-${width}.png`),fullPage:true})}
    }
   }
  }
  assert.deepEqual(await snapshot(),before,'layout/theme navigation changed business data');
  assert(requests.slice(writeStart).every(u=>new URL(u).hostname==='127.0.0.1'));
 });
 await check('nutrition rings use 4/4/9 energy only and preserve unknown and partial data',async()=>{
  await page.setViewportSize({width:390,height:844});await open('/');const home=await call('/home/'+day);
  const n=(known,unit='g',complete=true)=>({known,unit,complete,unknown:complete?0:1});
  const fixture={...home,record_count:1,nutrition:{...home.nutrition,energy:n(999,'kcal'),protein:n(10),carbs:n(20),fat:n(10)}};
  await page.route('**/api/home/*',r=>r.fulfill({contentType:'application/json',body:JSON.stringify(fixture)}));await open('/');
  const energy=page.getByTestId('home-energy');
  assert.equal(await energy.locator('.home-number').innerText(),'999');
  const ring=page.locator('.home-mobile-macros .macro-ring');
  assert.equal(await ring.getAttribute('data-macro-total'),'210');
  assert((await ring.getAttribute('aria-label')).includes('19.0%'));
  assert((await ring.getAttribute('aria-label')).includes('38.1%'));
  assert((await ring.getAttribute('aria-label')).includes('42.9%'));
  fixture.nutrition.protein=n(null);await page.reload();await energy.waitFor();
  assert.equal(await page.locator('.home-mobile-macros .macro-ring').count(),0);
  assert((await page.locator('.home-mobile-macros').innerText()).includes('数据不足'));
  fixture.nutrition.protein=n(10,'g',false);await page.reload();await energy.waitFor();
  assert.equal(await page.locator('.home-mobile-macros .macro-ring').count(),0);
  await page.unroute('**/api/home/*');
 });
 await check('feedback draft survives failure and mobile composer does not sit behind navigation',async()=>{
  await open('/feedback');await page.getByLabel('今天最明显的情况（选一项即可）').selectOption('饥饿');
  await page.getByText('补充其他感受（可选）',{exact:true}).click();
  await page.getByLabel('特殊情况（可选）').fill('界面回归测试，输入应保留');
  assert.equal(await page.locator('.mobile-primary-nav').isVisible(),false,'hide navigation while editing');
  await page.route('**/api/feedback/*',r=>r.request().method()==='PUT'?r.fulfill({status:503,contentType:'application/json',body:JSON.stringify({error:{message:'测试保存失败'}})}):r.continue());
  await page.getByRole('button',{name:'保存反馈并检查明日方案'}).click();await page.getByRole('alert').filter({hasText:'测试保存失败'}).waitFor();
  assert.equal(await page.getByLabel('特殊情况（可选）').inputValue(),'界面回归测试，输入应保留');
  assert.equal((await call('/feedback/'+day)).feedback,null);await page.unroute('**/api/feedback/*');
  await open('/chat');await page.getByLabel('你的问题',{exact:true}).fill('尚未发送');
  assert.equal(await page.locator('.mobile-primary-nav').isVisible(),false);assert.equal(await page.locator('.chat-composer textarea').inputValue(),'尚未发送');
 });
 await check('no page exceptions or third party traffic',async()=>{assert.deepEqual(errors,[]);assert(requests.every(u=>new URL(u).hostname==='127.0.0.1'))});
 console.log(JSON.stringify({passed:checks.length,output}));await call('/shutdown','POST',{});
}catch(e){console.error(e);process.exitCode=1;if(page)await page.screenshot({path:path.join(output,'failure.png'),fullPage:true}).catch(()=>{})}
finally{fs.writeFileSync(path.join(output,'results.json'),JSON.stringify({checks,errors,output},null,2));if(browser)await browser.close();if(server&&server.exitCode===null)server.kill()}})();
