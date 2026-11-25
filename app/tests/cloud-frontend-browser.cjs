'use strict';
// Browser plugin is unavailable; this test uses the bundled Playwright Edge runtime.
const {chromium}=require('C:/Users/hp/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules/playwright');
const assert=require('node:assert/strict');
const path=require('node:path');
const http=require('node:http');
const {spawn}=require('node:child_process');
const root=path.resolve(__dirname,'../..');
const apiPort=18886,webPort=18888;
const apiOrigin='http://localhost:'+apiPort,webOrigin='http://localhost:'+webPort;
let vite,browser,server;
const requests=[],pageErrors=[];
async function waitFor(url,child){
 for(let i=0;i<120;i++){
  if(child.exitCode!==null)throw new Error('server exited before ready');
  try{if((await fetch(url)).ok)return}catch{}
  await new Promise(resolve=>setTimeout(resolve,150));
 }
 throw new Error('timed out waiting for '+url);
}
(async()=>{
 try{
  // Synthetic cloud contract. Backend auth/RLS are covered separately against real PostgreSQL.
  server=http.createServer((req,res)=>{
   const cors={'Access-Control-Allow-Origin':webOrigin,'Access-Control-Allow-Credentials':'true','Vary':'Origin'};
   if(req.headers.origin!==webOrigin){res.writeHead(403,cors);res.end();return}
   if(req.method==='OPTIONS'){res.writeHead(204,{...cors,'Access-Control-Allow-Methods':'GET,POST,OPTIONS','Access-Control-Allow-Headers':'content-type,x-csrf-token'});res.end();return;}
   requests.push({method:req.method,path:req.url,cookie:req.headers.cookie||''});
   let payload;
   if(req.url==='/api/auth/session'){
    payload={authenticated:true,account_id:'synthetic-cloud-account',csrf:'test-csrf'};
    res.setHeader('Set-Cookie','shansuan_session=browser-credential-proof; Path=/; HttpOnly; SameSite=Lax');
   }else if(req.url==='/api/privacy/notice'){
    payload={notice_version:'test-v1',draft:true,text:'Synthetic privacy notice'};
   }else if(req.url==='/api/privacy/consent'){
    if(!String(req.headers.cookie||'').includes('shansuan_session=browser-credential-proof')){res.writeHead(401,cors);res.end('{}');return;}
    payload={accepted:false,notice_version:'test-v1'};
   }else{res.writeHead(404,cors);res.end('{}');return;}
   res.writeHead(200,{...cors,'Content-Type':'application/json','Cache-Control':'no-store'});res.end(JSON.stringify(payload));
  });
  await new Promise((resolve,reject)=>{server.once('error',reject);server.listen(apiPort,'127.0.0.1',resolve)});
  vite=spawn(process.execPath,[path.join(root,'app/frontend/node_modules/vite/bin/vite.js'),'--host','localhost','--port',String(webPort),'--strictPort'],{
   cwd:path.join(root,'app/frontend'),windowsHide:true,stdio:'ignore',env:{...process.env,VITE_API_BASE_URL:apiOrigin}});
  await waitFor(webOrigin,vite);
  browser=await chromium.launch({channel:'msedge',headless:true});
  const context=await browser.newContext({viewport:{width:1280,height:900}});
  const page=await context.newPage();
  page.on('pageerror',error=>pageErrors.push(error.message));
  await page.goto(webOrigin);
  await page.getByRole('heading',{name:'敏感个人信息处理单独同意'}).waitFor();
  assert(requests.some(r=>r.path==='/api/auth/session'),'cloud session bootstrap did not reach configured API origin');
  assert(requests.some(r=>r.path==='/api/privacy/consent'&&r.cookie.includes('shansuan_session=browser-credential-proof')),'cross-origin request did not send cloud session cookie');
  const cookie=(await context.cookies()).find(c=>c.name==='shansuan_session');
  assert(cookie?.httpOnly,'cloud session cookie must be HttpOnly');
  assert.equal(await page.evaluate(()=>document.cookie.includes('shansuan_session')),false);
  assert.equal(requests.some(r=>r.path==='/api/profile'||r.path==='/api/session'),false,'cloud login must not call local bootstrap or health routes before consent');
  assert.equal(pageErrors.length,0,'frontend page threw an exception');
  assert.equal(new URL(page.url()).origin,webOrigin);
  console.log('PASS cloud API host, credentialed HttpOnly session cookie, explicit-consent gate, and rendered app');
 }catch(error){console.error(error);process.exitCode=1}
 finally{if(browser)await browser.close();if(server)await new Promise(resolve=>server.close(resolve));if(vite&&vite.exitCode===null)vite.kill();}
})();
