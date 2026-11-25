'use strict';
// Uses the bundled Edge runtime because the Browser plugin is unavailable in this workspace.
const {chromium}=require('C:/Users/hp/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules/playwright');
const assert=require('node:assert/strict');
const http=require('node:http');
const {spawn}=require('node:child_process');
const path=require('node:path');
const root=path.resolve(__dirname,'../..');
const apiPort=18936,webPort=18937;
const apiOrigin=`http://localhost:${apiPort}`,webOrigin=`http://localhost:${webPort}`;
const state={authenticated:false,accepted:false,csrf:'cloud-csrf-test',calls:[],draft:null,rejectNextDraft:false};
let apiServer,vite,browser;
function send(res,status,body,extra={}){res.writeHead(status,{'Access-Control-Allow-Origin':webOrigin,'Access-Control-Allow-Credentials':'true','Access-Control-Expose-Headers':'Content-Disposition','Vary':'Origin','Content-Type':'application/json',...extra});res.end(JSON.stringify(body));}
async function body(req){const chunks=[];for await(const c of req)chunks.push(c);return JSON.parse(Buffer.concat(chunks).toString()||'{}');}
async function waitFor(url,child){for(let i=0;i<100;i++){if(child.exitCode!==null)throw new Error('server exited before ready');try{const r=await fetch(url);if(r.ok)return}catch{}await new Promise(r=>setTimeout(r,100));}throw new Error('server timed out');}
(async()=>{
 try{
  apiServer=http.createServer(async(req,res)=>{
   if(req.method==='OPTIONS'){res.writeHead(204,{'Access-Control-Allow-Origin':webOrigin,'Access-Control-Allow-Credentials':'true','Access-Control-Allow-Methods':'GET,POST,PUT,DELETE,OPTIONS','Access-Control-Allow-Headers':'content-type,x-csrf-token','Access-Control-Expose-Headers':'Content-Disposition','Vary':'Origin'});return res.end();}
   const url=new URL(req.url,apiOrigin);state.calls.push(`${req.method} ${url.pathname}`);
   if(url.pathname==='/api/auth/session')return send(res,200,{authenticated:state.authenticated,...(state.authenticated?{account_id:'acct-test',csrf:state.csrf}:{})});
   if(url.pathname==='/api/profile'&&req.method==='GET')return send(res,200,{profile:null,draft:state.draft,targets:{},measurements:[]});
   if(url.pathname==='/api/profile/draft'&&req.method==='PUT'){assert.equal(req.headers['x-csrf-token'],state.csrf);if(state.rejectNextDraft){state.rejectNextDraft=false;state.accepted=false;return send(res,428,{detail:'请重新同意当前说明'});}assert(state.accepted);const data=await body(req);state.draft={...data,version:data.version+1};return send(res,200,state.draft);}
   if(url.pathname==='/api/privacy/notice')return send(res,200,{notice_version:'test-v1',draft:true,text:'本说明为测试草案。健康属于敏感个人信息。您可以撤回同意。存储地点为中国大陆。'});
   if(url.pathname==='/api/auth/login'&&req.method==='POST'){state.authenticated=true;return send(res,200,{account_id:'acct-test',csrf:state.csrf},{'Set-Cookie':'shansuan_session=test-session; Path=/; HttpOnly; SameSite=Lax'});}
   if(url.pathname==='/api/auth/logout'&&req.method==='POST'){state.authenticated=false;state.accepted=false;return send(res,204,{}, {'Set-Cookie':'shansuan_session=; Path=/; Max-Age=0; HttpOnly; SameSite=Lax'});}
   if(url.pathname==='/api/privacy/consent'&&req.method==='GET')return send(res,200,{accepted:state.accepted,notice_version:'test-v1'});
   if(url.pathname==='/api/privacy/consent'&&req.method==='POST'){assert.equal(req.headers['x-csrf-token'],state.csrf);const data=await body(req);assert.equal(data.confirmed,true);state.accepted=true;return send(res,200,{accepted:true,notice_version:'test-v1'});}
   if(url.pathname==='/api/privacy/consent/withdraw'&&req.method==='POST'){assert.equal(req.headers['x-csrf-token'],state.csrf);state.accepted=false;return send(res,200,{accepted:false,notice_version:'test-v1'});}
   if(url.pathname==='/api/privacy/export'&&req.method==='POST'){assert.equal(req.headers['x-csrf-token'],state.csrf);assert.equal((await body(req)).password,'reauth-password');return send(res,200,{format:'shansuan-account-export-v1'},{'Content-Disposition':'attachment; filename="shansuan-export-test.json"'});}
   if(url.pathname==='/api/privacy/account'&&req.method==='DELETE'){assert.equal(req.headers['x-csrf-token'],state.csrf);const data=await body(req);assert.equal(data.password,'reauth-password');assert.equal(data.confirmation,'删除我的云端账户及全部数据');state.authenticated=false;state.accepted=false;return send(res,200,{deleted:true,retention_note:'测试保留说明'});}
   return send(res,404,{detail:'not found'});
  });
  await new Promise(r=>apiServer.listen(apiPort,'127.0.0.1',r));
  vite=spawn(process.execPath,[path.join(root,'app/frontend/node_modules/vite/bin/vite.js'),'--host','localhost','--port',String(webPort),'--strictPort'],{cwd:path.join(root,'app/frontend'),windowsHide:true,stdio:'ignore',env:{...process.env,VITE_API_BASE_URL:apiOrigin}});
  await waitFor(webOrigin,vite);
  browser=await chromium.launch({channel:'msedge',headless:true});
  const page=await browser.newPage();
  const pageErrors=[];page.on('pageerror',error=>pageErrors.push(error.message));
  await page.goto(webOrigin);
  await page.getByRole('heading',{name:'膳算云端'}).waitFor();
  assert.equal(await page.getByRole('checkbox',{name:/敏感个人信息/}).count(),0,'consent is unavailable before login');
  await page.getByLabel('邮箱').fill('tester@example.test');
  await page.getByLabel('密码').fill('correct-horse-battery');
  await page.getByRole('button',{name:'登录'}).click();
  await page.getByText('敏感个人信息处理单独同意').waitFor();
  assert.match(await page.locator('.cloud-portal-privacy-tools').innerText(),/云端备份尚未配置/);
  assert.doesNotMatch(await page.locator('.cloud-portal-privacy-tools').innerText(),/已配置的云端备份按公示保留期限到期清理/);
  const consent=page.getByRole('checkbox',{name:/敏感个人信息/});
  assert.equal(await consent.isChecked(),false,'consent checkbox must default unchecked');
  assert.equal(await page.getByRole('button',{name:'同意并继续'}).isDisabled(),true);
  assert.equal(state.calls.some(x=>x.includes('/api/profile')),false,'no health request is allowed before consent');
  await page.getByText(/阅读隐私说明/).click();
  assert.match(await page.locator('[data-testid="privacy-notice"]').innerText(),/撤回/);
  await consent.check();
  await page.getByRole('button',{name:'同意并继续'}).click();
  await page.getByRole('heading',{name:'认识你，从一份档案开始'}).waitFor();
  await page.screenshot({path:require('node:os').tmpdir()+'/shansuan-cloud-workspace.png',fullPage:false});
  assert(state.calls.includes('GET /api/profile'),'consented account must enter the real cloud profile flow');
  assert.equal(state.calls.some(x=>x.includes('/api/session')),false,'cloud business UI must not call the local session endpoint');
  assert.match(await page.getByText(/分六步填写/).innerText(),/仅保存在你的云端账户/);
  await page.getByLabel('年龄（岁）',{exact:true}).fill('32');
  await page.getByText('草稿已保存在你的云端账户',{exact:true}).waitFor();
  assert.equal(state.draft.values.age,32);
  await page.setViewportSize({width:390,height:844});
  assert(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth+1),'cloud mobile workspace horizontal overflow');
  await page.getByRole('button',{name:'更多功能',exact:true}).click();
  await page.getByRole('dialog').waitFor();
  assert.equal(await page.getByRole('button',{name:'手动保存',exact:true}).count(),0,'cloud menu cannot invoke local backup');
  assert.equal(await page.getByRole('link',{name:'拍照分析',exact:true}).count(),0,'cloud photo UI remains unavailable until storage is ready');
  await page.keyboard.press('Escape');
  await page.screenshot({path:require('node:os').tmpdir()+'/shansuan-cloud-workspace-mobile.png',fullPage:false});
  await page.setViewportSize({width:1280,height:720});
  await page.getByRole('button',{name:'账户与隐私'}).click();
  await page.getByRole('button',{name:'撤回健康信息处理同意'}).waitFor();
  await page.getByRole('button',{name:'撤回健康信息处理同意'}).click();
  await page.getByText('敏感个人信息处理单独同意').waitFor();
  assert.equal(await page.getByRole('heading',{name:'认识你，从一份档案开始'}).count(),0,'withdrawal unmounts health UI');
  await page.getByLabel('账户密码（复验）').fill('reauth-password');
  const exportDownload=page.waitForEvent('download');
  await page.getByRole('button',{name:'导出我的云端数据'}).click();
  assert.equal((await exportDownload).suggestedFilename(),'shansuan-export-test.json');
  await page.getByLabel('删除确认语').fill('删除我的云端账户及全部数据');
  await page.getByRole('button',{name:'永久删除云端账户'}).click();
  await page.getByRole('button',{name:'登录'}).waitFor();
  // A second account in the same browser must not see the first account's cached draft.
  state.draft=null;state.csrf='second-account-csrf';state.accepted=true;
  await page.getByLabel('邮箱').fill('second@example.test');
  await page.getByLabel('密码',{exact:true}).fill('second-account-password');
  await page.getByRole('button',{name:'登录',exact:true}).click();
  await page.getByRole('heading',{name:'认识你，从一份档案开始'}).waitFor();
  assert.equal(await page.getByLabel('年龄（岁）',{exact:true}).inputValue(),'');
  await page.getByLabel('年龄（岁）',{exact:true}).fill('40');
  await page.getByText('草稿已保存在你的云端账户',{exact:true}).waitFor();
  assert.equal(state.draft.values.age,40);
  state.rejectNextDraft=true;
  await page.getByLabel('年龄（岁）',{exact:true}).fill('41');
  await page.getByText('敏感个人信息处理单独同意',{exact:true}).waitFor();
  assert.equal(await page.getByRole('heading',{name:'认识你，从一份档案开始'}).count(),0,'server-side consent expiry closes the health workspace');
  assert.equal(state.draft.values.age,40,'rejected write cannot persist a draft');
  assert.deepEqual(pageErrors,[],'cloud business UI must not throw rendering exceptions');
  assert(state.calls.includes('POST /api/privacy/export'));
  assert(state.calls.includes('DELETE /api/privacy/account'));
  assert(state.calls.includes('POST /api/privacy/consent'));
  assert(state.calls.includes('POST /api/privacy/consent/withdraw'));
  assert(state.calls.includes('GET /api/profile'),'consented cloud app must use the cloud profile endpoint');
  assert.equal(state.calls.some(x=>x.includes('/api/session')),false,'cloud app must not fall through to the local session endpoint');
  console.log('PASS cloud login is isolated from local API; explicit consent defaults off and can be withdrawn');
 }catch(e){console.error(e);process.exitCode=1;}
 finally{if(browser)await browser.close();if(vite&&vite.exitCode===null)vite.kill();if(apiServer)await new Promise(r=>apiServer.close(r));}
})();

