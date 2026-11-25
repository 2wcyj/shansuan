'use strict';
// Browser plugin not available. Exercise the real React UI with Edge and a synthetic cloud API.
const {chromium}=require('C:/Users/hp/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules/playwright');
const assert=require('node:assert/strict');
const http=require('node:http');
const path=require('node:path');
const os=require('node:os');
const {spawn}=require('node:child_process');
const root=path.resolve(__dirname,'../..');
const apiOrigin='http://localhost:18946',webOrigin='http://localhost:18947';
const product={id:'synthetic-product',name:'合成测试食品',brand:'测试品牌',category:'测试',verification:'待核实',sale_status:'未确认',unit:'g',version:1,nutrients:{},serving_nutrients:{},allergens:[],allergens_confirmed:false,forms:[],tastes:[],diet_types:[],price:null,illustration:{},hidden:false,archived:false};
const settings={enabled:false,version:1};
const match={eligible:false,reasons:['正式资料待核实'],alternatives:['普通食物'],commercial:'自有产品 · 推广内容'};
const calls=[],errors=[],unexpected=[];
let browser,vite,server;
async function body(req){const chunks=[];for await(const c of req)chunks.push(c);return JSON.parse(Buffer.concat(chunks).toString()||'{}');}
async function ready(){for(let i=0;i<120;i++){if(vite.exitCode!==null)throw Error('Vite exited');try{if((await fetch(webOrigin)).ok)return}catch{}await new Promise(r=>setTimeout(r,100));}throw Error('Vite did not start');}
(async()=>{try{
 server=http.createServer(async(req,res)=>{
  const headers={'Access-Control-Allow-Origin':webOrigin,'Access-Control-Allow-Credentials':'true','Access-Control-Allow-Headers':'content-type,x-csrf-token','Access-Control-Allow-Methods':'GET,POST,PUT,OPTIONS','Content-Type':'application/json','Cache-Control':'no-store'};
  if(req.method==='OPTIONS'){res.writeHead(204,headers);return res.end();}
  const route=new URL(req.url,apiOrigin).pathname;calls.push(`${req.method} ${route}`);
  let payload,status=200;
  if(route==='/api/auth/session')payload={authenticated:true,account_id:'synthetic-account',csrf:'cloud-product-csrf'};
  else if(route==='/api/privacy/notice')payload={notice_version:'test',draft:true,text:'合成测试说明'};
  else if(route==='/api/privacy/consent')payload={accepted:true};
  else if(route==='/api/profile')payload={profile:{id:'main'},draft:null,targets:{},measurements:[]};
  else if(route==='/api/products')payload={items:[product],settings,recommendations:[]};
  else if(route==='/api/products/settings'){
   assert.equal(req.headers['x-csrf-token'],'cloud-product-csrf');const data=await body(req);settings.enabled=data.enabled;settings.version++;payload=settings;
  }else if(route==='/api/products/synthetic-product'&&req.method==='GET'){
   // Even if a future API returns metadata, the unimplemented file route must not be fetched.
   payload={product,match,files:[{id:'synthetic-file',role:'main',name:'合成图片.jpg'}]};
  }else if(route==='/api/products/synthetic-product'&&req.method==='PUT'){
   assert.equal(req.headers['x-csrf-token'],'cloud-product-csrf');const data=await body(req);assert.equal(data.version,product.version);assert(data.request_key);Object.assign(product,data,{version:product.version+1});payload=product;
  }else{unexpected.push(`${req.method} ${route}`);payload={detail:'未启用的测试接口'};status=404;}
  res.writeHead(status,headers);res.end(JSON.stringify(payload));
 });
 await new Promise((resolve,reject)=>{server.once('error',reject);server.listen(18946,'127.0.0.1',resolve)});
 vite=spawn(process.execPath,[path.join(root,'app/frontend/node_modules/vite/bin/vite.js'),'--host','localhost','--port','18947','--strictPort'],{cwd:path.join(root,'app/frontend'),windowsHide:true,stdio:'ignore',env:{...process.env,VITE_API_BASE_URL:apiOrigin}});
 await ready();browser=await chromium.launch({channel:'msedge',headless:true});
 const page=await browser.newPage({viewport:{width:1280,height:900}});page.on('pageerror',e=>errors.push(e.message));
 await page.goto(webOrigin+'/products');
 await page.getByRole('heading',{name:'我的产品',exact:true}).waitFor();
 assert.match(await page.locator('.page-products').innerText(),/云端账户私有目录/,'cloud catalogue must describe its real storage mode');
 assert.doesNotMatch(await page.locator('.page-products').innerText(),/本机私有目录|仅使用本机档案|不上传健康信息/,'cloud UI must not promise local-only storage');
 await page.getByRole('checkbox',{name:'启用自有产品推荐'}).check();
 await page.getByRole('heading',{name:'自有产品推荐',exact:true}).waitFor();
 assert(settings.enabled,'cloud settings must still save through the cloud API');
 await page.getByRole('link',{name:'测试品牌 · 合成测试食品',exact:true}).click();
 await page.getByRole('heading',{name:product.name,exact:true}).waitFor();
 await page.getByText(/云端产品附件尚未启用/).waitFor();
 assert.equal(await page.locator('input[type=file]').count(),0,'cloud cannot offer local attachment upload');
 assert.equal(await page.getByRole('button',{name:'导出文件',exact:true}).count(),0,'cloud cannot offer unimplemented attachment export');
 assert.equal(await page.locator('img.product-image').count(),0,'cloud cannot load unimplemented image endpoints');
 assert(await page.getByRole('button',{name:'主动加入餐食计划',exact:true}).isDisabled(),'unverified product still cannot enter a plan');
 assert(await page.getByRole('button',{name:'确认实际吃过',exact:true}).isDisabled(),'unverified product still cannot count as intake');
 await page.getByRole('button',{name:'编辑产品',exact:true}).click();
 await page.getByLabel('产品简介',{exact:true}).fill('合成测试修改');
 await page.getByRole('button',{name:'保存产品资料',exact:true}).click();
 await page.getByRole('dialog').waitFor({state:'detached'});
 await page.getByText('合成测试修改',{exact:true}).waitFor();
 assert.equal(product.description,'合成测试修改','regular product editing must remain usable');
 for(const theme of ['dark','light']){
  await page.getByRole('button',{name:theme==='dark'?'使用深色外观':'使用浅色外观'}).click();
  for(const width of [1280,390]){
   await page.setViewportSize({width,height:900});
   assert(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth+1),'cloud product detail must not overflow');
   await page.screenshot({path:path.join(os.tmpdir(),`shansuan-cloud-products-${theme}-${width}.png`),fullPage:false});
  }
  await page.setViewportSize({width:1280,height:900});
 }
 assert.equal(new URL(page.url()).pathname,'/products/synthetic-product');
 assert.deepEqual(errors,[],'cloud catalogue must render without runtime errors');
 assert.deepEqual(unexpected,[],'cloud product pages must not request local session/model/files/backup endpoints');
 console.log('PASS cloud product storage disclosure, unavailable attachments, verified-intake gates, settings/editing, dark/light and desktop/mobile layout');
}catch(e){console.error(e);process.exitCode=1}finally{if(browser)await browser.close();if(vite&&vite.exitCode===null)vite.kill();if(server)await new Promise(r=>server.close(r));}})();
