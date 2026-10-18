'use strict';
const assert=require('node:assert/strict'),path=require('node:path');

// Presentation and real interactions on the same isolated, encrypted test store.
module.exports=async({page,open,call,check,day,output})=>{
  const number=value=>value==null?'—':value.toLocaleString('zh-CN',{maximumFractionDigits:1,useGrouping:false});
  const card=kind=>page.getByTestId('home-'+kind);
  async function layout(width){
    await page.setViewportSize({width,height:900});
    await card('feelings').waitFor();
    const issue=await page.evaluate(()=>{
      if(document.documentElement.scrollWidth>innerWidth+1)return 'horizontal overflow';
      const cards=[...document.querySelectorAll('.weather-card')];
      const first=cards[0].getBoundingClientRect();
      for(const card of cards){
        const bounds=card.getBoundingClientRect();
        if(Math.abs(bounds.x-first.x)>1||Math.abs(bounds.width-first.width)>1)return 'cards not in a single column';
        const copy=card.querySelector('.home-card-copy').getBoundingClientRect();
        const value=card.querySelector('.home-value')?.getBoundingClientRect();
        if(value&&copy.right>value.left+1)return 'number overlaps description';
        for(const item of card.querySelectorAll('.home-card-copy,.home-value,.home-card-note,.home-card-meta')){
          const b=item.getBoundingClientRect();
          if(b.left<bounds.left||b.right>bounds.right||b.bottom>bounds.bottom)return 'card content clipped';
        }
      }
      return null;
    });
    assert.equal(issue,null,`homepage at ${width}px: ${issue}`);
    await page.evaluate(()=>window.scrollTo(0,document.body.scrollHeight));
    assert(await page.evaluate(()=>document.querySelector('.weather-feelings').getBoundingClientRect().bottom<document.querySelector('.home-assistant-dock').getBoundingClientRect().top),'floating bar covers last card');
    await page.evaluate(()=>window.scrollTo(0,0));
  }

  await check('homepage real nutrients, private save menu, keyboard and meal destination',async()=>{
    await open('/');
    const data=await call('/home/'+day);
    assert.equal(await card('energy').locator('.home-number').innerText(),String(Math.round(data.nutrition.energy.known)));
    assert.equal(await card('protein').locator('.home-number').innerText(),number(data.nutrition.protein.known));
    assert.equal(await page.locator('.weather-card').count(),5);
    const next=data.plan.meals.find(m=>m.status==='pending'&&m.recommendation);
    await card('meal').getByRole('link').click();
    const target=page.locator('[id="meal-'+next.id+'"]');
    await target.waitFor();
    assert((await target.innerText()).includes(next.recommendation.name));
    assert(await target.getByRole('button',{name:'替换',exact:true}).isEnabled());
    await target.locator('summary').click();
    assert((await target.innerText()).includes(next.recommendation.steps));
    await open('/');
    const more=page.getByRole('button',{name:'更多功能',exact:true});
    await more.click();
    assert(await page.getByRole('dialog').evaluate(d=>d.contains(document.activeElement)));
    await page.keyboard.press('Escape');
    await page.getByRole('dialog').waitFor({state:'detached'});
    assert(await more.evaluate(button=>button===document.activeElement));
    await more.click();
    await page.screenshot({path:path.join(output,'home-menu-1280.png')});
    const before=(await call('/data/backups')).items.map(b=>b.name);
    await page.getByRole('button',{name:'手动保存',exact:true}).click();
    await page.getByText('本机加密备份已保存',{exact:false}).waitFor();
    assert((await call('/data/backups')).items.some(b=>b.name.startsWith('manual-')&&!before.includes(b.name)&&b.bytes>0));
    await page.keyboard.press('Escape');
  });

  await check('homepage water save, failure preservation, pending disable and reload',async()=>{
    const before=(await call('/records?date='+day)).life?.water_ml??0;
    await page.route('**/api/life/water',route=>route.fulfill({status:503,contentType:'application/json',body:JSON.stringify({error:{message:'测试注入：饮水保存失败'}})}));
    await page.getByRole('button',{name:'添加200ml饮水记录'}).click();
    await card('water').getByRole('alert').waitFor();
    assert.equal((await call('/records?date='+day)).life?.water_ml??0,before);
    await page.unroute('**/api/life/water');
    let release;
    const barrier=new Promise(resolve=>release=resolve);
    await page.route('**/api/life/water',async route=>{await barrier;await route.continue()});
    const add=page.getByRole('button',{name:'添加200ml饮水记录'});
    await add.click();
    assert(await add.isDisabled());
    release();
    await card('water').getByRole('status').filter({hasText:'已增加200ml'}).waitFor();
    await page.unroute('**/api/life/water');
    await page.reload();
    await card('water').waitFor();
    assert.equal(await card('water').locator('.home-number').innerText(),String(before+200));
    assert.equal((await call('/records?date='+day)).life.water_ml,before+200);
    assert((await card('water').innerText()).includes('未记录单次时间'));
  });

  await check('homepage recent feelings reflect saved feedback, chat and camera remain accessible',async()=>{
    await card('feelings').getByText('记录后生成',{exact:true}).waitFor();
    assert(!(await card('feelings').innerText()).includes('评分'));
    await card('feelings').getByRole('link',{name:'查看今日反馈'}).click();
    await page.getByText('补充其他感受（可选）',{exact:true}).click();
    await page.getByLabel('饥饿与饱腹感').selectOption('合适');
    await page.getByLabel('精力状态').selectOption('良好');
    await page.getByLabel('口味感受').selectOption('合适');
    await page.getByRole('button',{name:'保存反馈并检查明日方案'}).click();
    await page.getByRole('heading',{name:/明日方案/}).waitFor();
    await open('/');
    await card('feelings').locator('dl').waitFor();
    const feedback=(await call('/feedback/'+day)).feedback;
    assert.deepEqual(await card('feelings').locator('dd').allTextContents(),[feedback.hunger,feedback.energy,feedback.taste]);
    await page.getByRole('link',{name:'今天吃什么？问问你的营养助手',exact:true}).click();
    await page.getByLabel('你的问题',{exact:true}).waitFor();
    await open('/');
    await page.getByRole('link',{name:'拍照分析食物',exact:true}).click();
    await page.getByLabel('选择照片（JPG / PNG / WebP，最多12MB）').waitFor();
    await open('/');
  });

  await check('homepage 320/390/1280/1440 layouts and real page screenshots',async()=>{
    for(const width of [320,390,1280,1440]){
      await layout(width);
      await page.screenshot({path:path.join(output,`home-${width}.png`),fullPage:true});
    }
    await page.setViewportSize({width:390,height:844});
    await page.screenshot({path:path.join(output,'home-390-viewport.png')});
    await page.evaluate(()=>window.scrollTo(0,document.body.scrollHeight));
    await page.screenshot({path:path.join(output,'home-390-bottom.png')});
    await page.setViewportSize({width:1280,height:1280});
    await page.evaluate(()=>window.scrollTo(0,0));
    await page.screenshot({path:path.join(output,'home-desktop-overview.png')});
    await page.evaluate(()=>document.documentElement.style.fontSize='22.5px');
    await layout(390);
    await page.evaluate(()=>document.documentElement.style.fontSize='');
  });

  await check('homepage missing data, long values, loading, errors and accessibility preferences',async()=>{
    const real=await call('/home/'+day),report=await call('/reports?end='+day);
    const routeHome=async body=>{await page.route('**/api/home/*',route=>route.fulfill({contentType:'application/json',body:JSON.stringify(body)}));await open('/')};
    const blank={...real,records:[],record_count:0,life:null,coverage:'没有饮食记录',nutrition:{...real.nutrition,energy:{...real.nutrition.energy,known:null},protein:{...real.nutrition.protein,known:null}}};
    await page.route('**/api/reports?*',route=>route.fulfill({contentType:'application/json',body:JSON.stringify({...report,days:report.days.map(d=>({...d,feedback:null}))})}));
    await routeHome(blank);
    await card('feelings').getByText('记录后生成',{exact:true}).waitFor();
    for(const kind of ['energy','protein','water'])assert.equal(await card(kind).locator('.home-number').innerText(),'—');
    await page.unroute('**/api/home/*');
    await page.unroute('**/api/reports?*');
    const long={...real,profile:{...real.profile,primary_goal:'日常营养均衡及长期生活习惯管理',goals:['日常营养均衡及长期生活习惯管理','补充蛋白质']},life:{...real.life,water_ml:12000},nutrition:{...real.nutrition,energy:{...real.nutrition.energy,known:12345},protein:{...real.nutrition.protein,known:1234.5}}};
    await routeHome(long);
    await layout(320);await layout(390);
    assert.equal(await card('energy').locator('.home-number').innerText(),'12345');
    await page.emulateMedia({reducedMotion:'reduce'});
    assert.equal(await card('energy').evaluate(el=>getComputedStyle(el).transitionDuration),'0s');
    const cdp=await page.context().newCDPSession(page);
    await cdp.send('Emulation.setEmulatedMedia',{features:[{name:'prefers-reduced-transparency',value:'reduce'}]});
    assert.equal(await page.locator('.home-assistant-dock').evaluate(el=>getComputedStyle(el).backdropFilter),'none');
    await cdp.send('Emulation.setEmulatedMedia',{features:[]});await cdp.detach();
    await page.emulateMedia({reducedMotion:'no-preference'});
    await page.unroute('**/api/home/*');
    await page.route('**/api/home/*',route=>route.fulfill({status:503,contentType:'application/json',body:JSON.stringify({error:{message:'测试注入：首页暂不可读'}})}));
    await open('/');
    await page.getByRole('alert').filter({hasText:'首页暂不可读'}).waitFor();
    await page.unroute('**/api/home/*');
    await page.getByRole('button',{name:'重试',exact:true}).click();
    await card('energy').waitFor();
    let release;
    const barrier=new Promise(resolve=>release=resolve);
    await page.route('**/api/home/*',async route=>{await barrier;await route.continue()});
    await open('/');
    await page.getByRole('status').filter({hasText:'正在读取本机文件'}).waitFor();
    assert.equal(await page.locator('.home-skeletons>div').count(),5);
    release();await card('energy').waitFor();await page.unroute('**/api/home/*');
    assert(!/天气|温度|城市|健康评分/.test(await page.locator('.home-content').innerText()));
    await page.setViewportSize({width:1280,height:900});
  });
};
