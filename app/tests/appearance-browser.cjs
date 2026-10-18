'use strict';
const assert=require('node:assert/strict'),path=require('node:path');

// Exercises appearance on the real application and the harness's isolated files.
// Its own browser context keeps preference testing separate from file-persistence tests.
module.exports=async({browser,url,call,check,day,output})=>{
  const context=await browser.newContext({viewport:{width:1280,height:900},colorScheme:'dark'});
  const page=await context.newPage(),errors=[],requests=[];
  page.on('pageerror',error=>errors.push(error.message));
  page.on('request',request=>requests.push({url:request.url(),method:request.method()}));
  await page.route('**/*',route=>new URL(route.request().url()).hostname==='127.0.0.1'?route.continue():route.abort());
  const waitTheme=theme=>page.waitForFunction(theme=>document.documentElement.dataset.theme===theme,theme);
  async function open(route){await page.goto(url+route);await page.locator('h1').first().waitFor();await page.locator('.card,.weather-card').first().waitFor()}
  async function switchTo(theme){
    const label={dark:'深色',light:'浅色',system:'跟随系统'}[theme];
    await page.getByRole('button',{name:'使用'+label+'外观',exact:true}).click();
    if(theme!=='system')await waitTheme(theme);
    await page.waitForTimeout(260);
  }
  const business=async()=>Promise.all(['/profile','/records?date='+day,'/plans/'+day,'/feedback/'+day,'/reports?end='+day,'/analyses','/chats'].map(route=>call(route)));
  const before=await business();
  try{
    await check('appearance system theme, unsaved profile, route and scroll are preserved',async()=>{
      await open('/profile');await waitTheme('dark');
      assert.equal(await page.getByRole('button',{name:'使用跟随系统外观'}).getAttribute('aria-pressed'),'true');
      await page.getByLabel('年龄（岁）',{exact:true}).fill('37');
      await page.evaluate(()=>window.scrollTo(0,180));
      const scroll=await page.evaluate(()=>scrollY),route=page.url(),marker=await page.evaluate(()=>window.__appearanceMarker={});
      await page.evaluate(()=>document.querySelector('button[aria-label="使用浅色外观"]').click());
      await waitTheme('light');await page.waitForTimeout(260);
      assert.equal(await page.getByLabel('年龄（岁）',{exact:true}).inputValue(),'37');
      assert.equal(page.url(),route);assert.equal(await page.evaluate(()=>scrollY),scroll);
      assert(await page.evaluate(()=>!!window.__appearanceMarker),'theme selection reloaded the document');
      assert.equal(marker&&typeof marker,'object');
      await switchTo('dark');assert.equal(await page.getByLabel('年龄（岁）',{exact:true}).inputValue(),'37');
    });
    await check('appearance preference persists and follows live system changes',async()=>{
      await open('/profile');await switchTo('light');await page.reload();await waitTheme('light');
      assert.equal(await page.evaluate(()=>localStorage.getItem('shansuan.appearance')),'light');
      await page.emulateMedia({colorScheme:'dark'});await waitTheme('light');
      await switchTo('system');await waitTheme('dark');
      await page.emulateMedia({colorScheme:'light'});await waitTheme('light');
      await page.emulateMedia({colorScheme:'dark'});await waitTheme('dark');
      await switchTo('light');const tab=await context.newPage();await tab.goto(url+'/profile');
      await tab.waitForFunction(()=>document.documentElement.dataset.theme==='light');
      await tab.getByRole('button',{name:'使用深色外观'}).click();await waitTheme('dark');await tab.close();
      assert.deepEqual(await page.evaluate(()=>Object.keys(localStorage)),['shansuan.appearance']);
    });
    await check('appearance switches preserve chat draft and open record dialog',async()=>{
      await open('/chat');await page.locator('.chat-composer textarea').fill('尚未发送的饮食问题');
      await switchTo('light');await switchTo('dark');
      assert.equal(await page.locator('.chat-composer textarea').inputValue(),'尚未发送的饮食问题');
      await open('/records');await page.getByRole('button',{name:'＋ 记一餐',exact:true}).click();
      await page.getByLabel('选择食物添加',{exact:true}).selectOption('usda-168878');
      await page.getByLabel('第1项重量（g）').fill('177');
      const tab=await context.newPage();await tab.goto(url+'/profile');await tab.getByRole('button',{name:'使用浅色外观'}).click();
      await waitTheme('light');assert.equal(await page.getByLabel('第1项重量（g）').inputValue(),'177');
      assert(await page.locator('dialog').evaluate(el=>el.open&&el.contains(document.activeElement)));
      await page.screenshot({animations:'disabled',path:path.join(output,'appearance-dialog-light.png')});
      await tab.getByRole('button',{name:'使用深色外观'}).click();await waitTheme('dark');await page.waitForTimeout(260);
      await page.screenshot({animations:'disabled',path:path.join(output,'appearance-dialog-dark.png')});
      await tab.close();await page.keyboard.press('Escape');assert.equal(await page.locator('dialog').count(),0);
    });
    await check('appearance eight pages in both themes, responsive screenshots and text contrast',async()=>{
      for(const theme of ['dark','light']){
        await open('/profile');await switchTo(theme);
        for(const width of [1280,390,320]){
          await page.setViewportSize({width,height:900});
          for(const route of ['/','/meals','/photo','/chat','/records','/feedback','/report','/profile']){
            await open(route);await page.waitForTimeout(280);
            if(route==='/photo'){
              const history=page.getByLabel('本机照片历史');
              if(await history.count()){
                const value=await history.locator('option').nth(1).getAttribute('value');if(value)await history.selectOption(value);
              }
            }
            if(route==='/chat'){
              const history=page.getByLabel('本机对话');
              if(await history.locator('option').count()>1){
                await history.selectOption(await history.locator('option').nth(1).getAttribute('value'));
                await page.locator('.chat-turn.assistant').first().waitFor();
              }
            }
            assert.equal(await page.evaluate(()=>document.documentElement.dataset.theme),theme);
            assert(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth+1),`overflow ${theme} ${width} ${route}`);
            if(route==='/meals')assert(await page.evaluate(()=>{
              const cards=[...document.querySelectorAll('.page-meals>.grid>.card')];
              const grid=document.querySelector('.page-meals>.grid');
              const next=grid?.nextElementSibling;
              return !next||cards.every(card=>card.getBoundingClientRect().bottom+12<=next.getBoundingClientRect().top);
            }),`meal cards overlap nutrition summary ${width}`);
            const problems=await page.evaluate(()=>{
              function rgba(s){return(s.match(/[\d.]+/g)||[]).map(Number)}
              function over(a,b){const alpha=a[3]??1;return a.slice(0,3).map((v,i)=>v*alpha+b[i]*(1-alpha))}
              function lum(c){return c.map(v=>{v/=255;return v<=.04045?v/12.92:((v+.055)/1.055)**2.4}).reduce((v,x,i)=>v+x*[.2126,.7152,.0722][i],0)}
              const issues=[];
              for(const el of document.querySelectorAll('.muted,.field>span,nav>a,.badge,.home-subtitle,.home-card-note,.home-unit,.home-coverage')){
                if(!el.getClientRects().length)continue;
                let node=el,ancestors=[];while(node){ancestors.unshift(node);node=node.parentElement}
                let bg=rgba(getComputedStyle(document.documentElement).backgroundColor);
                for(const ancestor of ancestors)bg=over(rgba(getComputedStyle(ancestor).backgroundColor),bg);
                const fg=rgba(getComputedStyle(el).color),ratio=(Math.max(lum(fg),lum(bg))+.05)/(Math.min(lum(fg),lum(bg))+.05);
                if(ratio<4.5)issues.push({text:el.textContent.slice(0,40),ratio});
              }return issues;
            });
            assert.deepEqual(problems,[],`text contrast ${theme} ${route}`);
            if(width!==320)await page.screenshot({animations:'disabled',path:path.join(output,`appearance-${route.slice(1)||'home'}-${theme}-${width}.png`),fullPage:true});
          }
        }
      }
    });
    await check('appearance meal alternatives, profile tags and unobstructed overview screenshots',async()=>{
      for(const theme of ['dark','light']){
        await page.setViewportSize({width:1280,height:900});await open('/profile');await switchTo(theme);
        await page.getByRole('button',{name:'4. 健康与过敏原',exact:true}).click();
        await page.getByLabel('过敏信息是否已确认').selectOption('有');
        await page.getByRole('button',{name:'花生',exact:true}).click();
        assert.equal(await page.getByRole('button',{name:'花生 ✓',exact:true}).getAttribute('aria-pressed'),'true');
        await page.screenshot({animations:'disabled',path:path.join(output,`appearance-profile-tags-${theme}.png`),fullPage:true});
        await open('/meals');await page.getByRole('button',{name:'替换',exact:true}).first().click();
        await page.getByRole('dialog',{name:'选择替代餐食'}).waitFor();
        await page.getByRole('button',{name:'使用这个替代',exact:true}).first().waitFor();
        await page.screenshot({animations:'disabled',path:path.join(output,`appearance-alternatives-${theme}.png`)});
        await page.keyboard.press('Escape');
        await open('/');await page.getByRole('button',{name:'更多功能',exact:true}).click();
        await page.getByRole('dialog').waitFor();
        await switchTo(theme==='dark'?'light':'dark');await switchTo(theme);
        assert.equal(new URL(page.url()).pathname,'/');
        assert.equal(await page.locator('.home-menu nav a').count(),8);
        await page.screenshot({animations:'disabled',path:path.join(output,`appearance-home-menu-${theme}.png`)});
        await page.keyboard.press('Escape');
        await page.setViewportSize({width:1280,height:1280});await open('/');
        await page.getByTestId('home-feelings').waitFor();
        await page.screenshot({animations:'disabled',path:path.join(output,`appearance-home-${theme}-overview.png`)});
        await page.setViewportSize({width:390,height:844});
        await page.evaluate(()=>scrollTo(0,document.body.scrollHeight));
        assert(await page.evaluate(()=>document.querySelector('.weather-feelings').getBoundingClientRect().bottom<document.querySelector('.home-assistant-dock').getBoundingClientRect().top));
        await page.screenshot({animations:'disabled',path:path.join(output,`appearance-home-${theme}-bottom.png`)});
      }
    });
    await check('appearance loading, retry, disabled and accessibility material fallbacks',async()=>{
      await page.setViewportSize({width:1280,height:900});
      for(const theme of ['light','dark']){
        await open('/profile');await switchTo(theme);
        await page.route('**/api/records?*',route=>route.fulfill({status:503,contentType:'application/json',body:JSON.stringify({error:{message:'测试注入：记录暂不可读'}})}));
        await page.goto(url+'/records');await page.getByRole('alert').filter({hasText:'记录暂不可读'}).waitFor();
        await page.screenshot({animations:'disabled',path:path.join(output,`appearance-error-${theme}.png`)});
        await page.unroute('**/api/records?*');await page.getByRole('button',{name:'重试',exact:true}).click();await page.locator('.card').first().waitFor();
        let release;const barrier=new Promise(resolve=>release=resolve);
        await page.route('**/api/records?*',async route=>{await barrier;await route.continue()});
        await page.goto(url+'/records');await page.getByRole('status').filter({hasText:'正在读取本机文件'}).waitFor();
        release();await page.locator('.card').first().waitFor();await page.unroute('**/api/records?*');
        await page.getByRole('button',{name:'＋ 记一餐',exact:true}).click();
        assert(await page.getByRole('button',{name:'保存实际记录',exact:true}).isDisabled());
        await page.keyboard.press('Escape');
      }
      await page.emulateMedia({reducedMotion:'reduce'});
      assert.equal(await page.locator('.card').first().evaluate(el=>getComputedStyle(el).transitionDuration),'0s');
      const cdp=await context.newCDPSession(page);
      await cdp.send('Emulation.setEmulatedMedia',{features:[{name:'prefers-reduced-transparency',value:'reduce'}]});
      assert.equal(await page.locator('.card').first().evaluate(el=>getComputedStyle(el).backdropFilter),'none');
      assert.equal(await page.locator('aside').evaluate(el=>getComputedStyle(el).backdropFilter),'none');
      await cdp.detach();
    });
    await check('appearance makes no business writes, outside requests or page errors',async()=>{
      assert.deepEqual(await business(),before,'appearance changed stored business data');
      assert.equal(requests.filter(r=>new URL(r.url).pathname.startsWith('/api/')&&!['GET','HEAD'].includes(r.method)).length,0);
      assert(requests.every(r=>new URL(r.url).hostname==='127.0.0.1'));
      assert.deepEqual(errors,[]);
    });
  }catch(error){
    await page.screenshot({path:path.join(output,'appearance-failure.png'),fullPage:true}).catch(()=>{});
    throw error;
  }finally{await context.close()}
};
