'use strict';
// Browser plugin not available. Real Edge against an isolated encrypted database.
const {chromium}=require('C:/Users/hp/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules/playwright');
const assert=require('node:assert/strict'),fs=require('node:fs'),path=require('node:path'),os=require('node:os'),{spawn}=require('node:child_process');
const root=path.resolve(__dirname,'../..'),data=fs.mkdtempSync(path.join(os.tmpdir(),'shansuan-products-')),port=18881,url='http://127.0.0.1:'+port,output=path.join(root,'.test-output');
let server,browser;const errors=[],requests=[],checks=[];const pause=ms=>new Promise(r=>setTimeout(r,ms));
(async()=>{try{
 server=spawn(path.join(root,'.venv/Scripts/python.exe'),['app/scripts/run.py','--data-dir',data,'--port',String(port),'--no-browser','--no-model'],{cwd:root,windowsHide:true,env:{...process.env,PYTHONUTF8:'1'},stdio:'ignore'});
 for(let i=0;i<100;i++){try{if((await fetch(url+'/api/session')).ok)break}catch{}await pause(150)}
 browser=await chromium.launch({channel:'msedge',headless:true});const context=await browser.newContext({viewport:{width:1280,height:900}}),page=await context.newPage();
 page.on('pageerror',e=>errors.push(e.message));page.on('request',r=>requests.push(r.url()));
 await page.goto(url);
 async function call(route,method='GET',body){return page.evaluate(async({route,method,body})=>{const s=await fetch('/api/session').then(r=>r.json());const r=await fetch('/api'+route,{method,headers:{'Content-Type':'application/json','X-CSRF-Token':s.csrf},body:body===undefined?undefined:JSON.stringify(body)});const v=await r.json();if(!r.ok)throw Error(v.error.message);return v},{route,method,body})}
 const profile={sex:'女',age:30,height:165,weight:60,sleep_hours:7,exercise_weekly:2,activity:'轻度',lifestyle:'上班族',goals:['补充蛋白质'],primary_goal:'补充蛋白质',health_status:'明确无',allergy_status:'明确无'};
 await call('/profile','PUT',profile);const d=new Date().toLocaleDateString('en-CA');
 await page.goto(url);await page.getByRole('link',{name:/我的产品/}).click();await page.getByRole('heading',{name:'我的产品',exact:true}).waitFor();
 assert.equal((await call('/products')).items.length,6);
 await page.getByRole('link',{name:'千人千植 · 低脂蛋白棒',exact:true}).click();await page.getByRole('heading',{name:'低脂蛋白棒',exact:true}).waitFor();
 assert(await page.getByRole('button',{name:'确认实际吃过',exact:true}).isDisabled());assert.equal((await call('/records?date='+d)).record_count,0);checks.push('concept labels cannot be recommended or recorded');
 for(const theme of ['dark','light']){await page.getByRole('button',{name:theme==='dark'?'使用深色外观':'使用浅色外观'}).click();await page.screenshot({path:path.join(output,'products-concept-'+theme+'.png'),fullPage:true})}
 await page.goto(url+'/products');await page.getByRole('button',{name:'新增产品',exact:true}).click();await page.getByLabel('商品名称',{exact:true}).fill('测试专用正式食品');await page.getByRole('button',{name:'保存产品资料',exact:true}).click();await page.locator('dialog').waitFor({state:'detached'});
 await page.getByRole('link',{name:/测试专用正式食品/}).click();await page.getByRole('button',{name:'编辑产品',exact:true}).click();
 await page.getByLabel('资料核实状态').selectOption('已核实');await page.getByRole('button',{name:'保存产品资料'}).click();await page.locator('dialog').getByRole('alert').waitFor();assert.equal(await page.getByLabel('商品名称',{exact:true}).inputValue(),'测试专用正式食品');checks.push('incomplete verification rejected and form retained');
 await page.getByLabel('正式完整配料表',{exact:true}).fill('燕麦、水');await page.getByLabel('交叉污染声明',{exact:true}).fill('无已知交叉接触');await page.getByLabel('正式资料来源',{exact:true}).fill('测试标签 v1');await page.getByLabel('核实人',{exact:true}).fill('自动化测试');await page.getByLabel('核实日期（YYYY-MM-DD）',{exact:true}).fill(d);
 await page.getByRole('checkbox',{name:/我已核对完整配料/}).check();
 for(const [label,value] of [['热量（kcal/100g）','200'],['蛋白质（g/100g）','20'],['脂肪（g/100g）','5'],['碳水（g/100g）','20'],['钠（mg/100g）','100']])await page.getByLabel(label,{exact:true}).fill(value);
 await page.getByRole('button',{name:'保存产品资料'}).click();await page.locator('dialog').waitFor({state:'detached'});
 await page.getByRole('button',{name:'主动加入餐食计划'}).click();await page.getByLabel('食用分量（g）').fill('35');await page.getByRole('button',{name:'确认加入可选计划'}).click();await page.locator('dialog').waitFor({state:'detached'});assert.equal((await call('/records?date='+d)).record_count,0);checks.push('adding plan does not create actual intake');
 await page.goto(url+'/meals');await page.getByRole('button',{name:'核对并确认实际食用'}).click();await page.getByRole('checkbox',{name:/我确认实际已经食用/}).check();await page.getByRole('button',{name:'保存产品实际食用'}).click();await page.locator('dialog').waitFor({state:'detached'});assert.equal((await call('/records?date='+d)).nutrition.protein.known,7);checks.push('actual confirmation counts verified portion');
 await page.goto(url+'/records');await page.getByText('自有产品实际食用',{exact:true}).waitFor();await page.getByRole('button',{name:'修改',exact:true}).click();await page.getByLabel('实际分量（g）').fill('40');await page.getByRole('button',{name:'保存实际记录'}).click();await page.locator('dialog').waitFor({state:'detached'});assert.equal((await call('/records?date='+d)).nutrition.protein.known,8);
 await page.goto(url+'/products');await page.getByRole('checkbox',{name:'启用自有产品推荐'}).check();await page.getByRole('heading',{name:'自有产品推荐',exact:true}).waitFor();
 for(const theme of ['dark','light']){await page.getByRole('button',{name:theme==='dark'?'使用深色外观':'使用浅色外观'}).click();for(const width of [1280,390]){await page.setViewportSize({width,height:900});await page.screenshot({path:path.join(output,`products-${theme}-${width}.png`),fullPage:true});assert(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth+1))}}checks.push('dark light desktop and narrow layout');
 assert.deepEqual(errors,[]);assert(requests.every(u=>new URL(u).hostname==='127.0.0.1'));checks.push('no page errors or third party requests');
 fs.writeFileSync(path.join(output,'products-browser.json'),JSON.stringify({checks,data,errors},null,2));console.log(JSON.stringify({passed:checks.length,checks}));await call('/shutdown','POST',{});
 }catch(e){console.error(e);process.exitCode=1}finally{if(browser)await browser.close();if(server&&server.exitCode===null)server.kill()}})();
