"""Combinations of sourced edible weights, not measured Chinese dish analyses."""
import json
from pathlib import Path
foods=json.loads(Path('app/resources/foods.json').read_text(encoding='utf-8'))
by_id={f['id']:f for f in foods}
recipes=[]
def add(name,meal,pairs,method,minutes,cost,forms=None,steps=None):
    items=[{'food_id':'usda-'+str(id),'grams':grams} for id,grams in pairs]
    recipes.append(dict(id='recipe-'+str(len(recipes)+1),name=name,meals=meal,items=items,method=method,minutes=minutes,cost=cost,forms=forms or ['家庭烹饪','现做熟食'],taste='清淡',steps=steps or '按标示的生/熟可食重量准备。需要加热的食物充分加热至熟，搭配食用；组合不额外加盐糖。生熟重量不能互换；具体烹饪损失未另作测量。',source='应用自编组合；各原料按USDA来源计算；成本为非实时参考，实际油盐需另记'))
add('牛奶燕麦与香蕉',['早餐'],[(169705,45),(171267,250),(173944,100)],'煮',8,8)
add('水煮蛋红薯与苹果',['早餐'],[(173424,100),(168484,200),(171688,150)],'煮',15,9)
add('酸奶燕麦与蓝莓',['早餐'],[(170886,200),(169705,40),(171711,80)],'凉拌',5,12,['即食食品','方便携带的食物','家庭烹饪'])
add('豆腐玉米与小白菜',['早餐'],[(172448,130),(170440,160),(170391,150)],'蒸',15,9)
add('藜麦鸡蛋与黄瓜',['早餐'],[(168917,160),(173424,100),(168409,100)],'煮',15,12)
add('鹰嘴豆红薯与番茄',['早餐'],[(173757,140),(168484,180),(170457,100)],'蒸',10,9)
add('土豆鸡蛋与番茄',['早餐'],[(170686,220),(173424,100),(170457,150)],'煮',15,9)
add('糙米扁豆与南瓜',['早餐'],[(169704,160),(172421,150),(169296,180)],'炖',20,9)
grains=[168878,169704,168917,170686]
proteins=[171478,172448,175168,172389,171791,173757,172421,172449]
vegetables=[169967,170391,169980,170394,170397,169976,169141,169296]
stew_steps='按标示的生/熟可食重量准备。已熟食材与适量清水小火炖热并确保充分加热；清水未计入营养，配方中列出的油已计入，勿把生熟重量互换。'

for i in range(8):
    p=proteins[i];v=vegetables[i];g=grains[i%4]
    protein_name=by_id['usda-'+str(p)]['name'].split('（')[0]
    vegetable_name=by_id['usda-'+str(v)]['name'].split('（')[0]
    grain_name=by_id['usda-'+str(g)]['name'].split('（')[0]
    breakfast_pairs=[(g,140),(p,90),(v,120)]
    add(grain_name+protein_name+'与'+vegetable_name+'炖饭',['早餐'],breakfast_pairs,'炖',22,10+i,steps=stew_steps)
for i in range(8):
    for meal in ['午餐','晚餐']:
        p=proteins[i];v=vegetables[(i+(meal=='晚餐')*2)%8];g=grains[i%4]
        method='蒸' if i%2==0 else '煮'
        add(by_id['usda-'+str(p)]['name']+'配'+by_id['usda-'+str(v)]['name']+'与'+by_id['usda-'+str(g)]['name'],[meal],[(g,180),(p,130),(v,200),(171413,5)],method,12+i%4*4,14+i)
        stew_name=by_id['usda-'+str(p)]['name'].split('（')[0]+'与'+by_id['usda-'+str(v)]['name'].split('（')[0]+'炖饭'
        stew_pairs=[(g,180),(p,130),(v,200),(171413,5)]
        add(stew_name,[meal],stew_pairs,'炖',25,14+i,steps=stew_steps)
for name,pairs in [('苹果与酸奶',[(171688,150),(170886,150)]),('香蕉与牛奶',[(173944,100),(171267,200)]),('橙子与鹰嘴豆',[(169097,150),(173757,80)]),('蓝莓与南瓜籽',[(171711,100),(170556,15)]),('水煮蛋与猕猴桃',[(173424,50),(168153,100)]),('毛豆与黄瓜',[(168411,100),(168409,100)])]:
    add(name,['加餐'],pairs,'凉拌',5,7,['即食食品','方便携带的食物','家庭烹饪'])
Path('app/resources/recipes.json').write_text(json.dumps(recipes,ensure_ascii=False,indent=2),encoding='utf-8')
print(f'{len(recipes)} sourced combinations')
