"""Select traceable USDA entries; no model-generated nutrient values."""
import csv
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SOURCE = next((ROOT / '.tools/usda').glob('*/food.csv')).parent
# Chinese display names describe the source item, not an asserted Chinese brand.
SELECT = [
('白米饭','Rice, white, long-grain, regular, enriched, cooked','grain'),
('糙米饭','Rice, brown, long-grain, cooked','grain'),
('燕麦片（干）','Oats (Includes','grain'),
('熟荞麦','Buckwheat groats, roasted, cooked','grain'),
('熟荞麦面','Noodles, japanese, soba, cooked','grain'),
('熟细面','Noodles, japanese, somen, cooked','grain'),
('全麦面包','Bread, whole-wheat, commercially prepared','grain'),
('白面包','Bread, white, commercially prepared (includes soft bread crumbs)','grain'),
('熟小米','Millet, cooked','grain'),
('熟藜麦','Quinoa, cooked','grain'),
('水煮土豆','Potatoes, boiled, cooked without skin, flesh, without salt','vegetable'),
('蒸红薯参考（水煮）','Sweet potato, cooked, boiled, without skin','vegetable'),
('熟甜玉米','Corn, sweet, yellow, cooked, boiled, drained, without salt','vegetable'),
('鸡胸肉（炖熟）','Chicken, broilers or fryers, breast, meat only, cooked, stewed','meat'),
('鸡胸肉（烤熟）','Chicken, broilers or fryers, breast, meat only, cooked, roasted','meat'),
('鸡腿肉（炖熟）','Chicken, broilers or fryers, thigh, meat only, cooked, stewed','meat'),
('猪里脊（烤熟）','Pork, fresh, loin, tenderloin, separable lean only, cooked, roasted','meat'),
('牛肉（熟瘦肉参考）','Beef, ground, 95% lean meat / 5% fat, patty, cooked, broiled','meat'),
('三文鱼（熟）','Fish, salmon, Atlantic, farmed, cooked, dry heat','fish'),
('鳕鱼（熟）','Fish, cod, Atlantic, cooked, dry heat','fish'),
('罗非鱼（熟）','Fish, tilapia, cooked, dry heat','fish'),
('虾（熟）','Crustaceans, shrimp, mixed species, cooked, moist heat','fish'),
('水煮鸡蛋','Egg, whole, cooked, hard-boiled','egg'),
('水煮蛋白','Egg, white, cooked','egg'),
('硬豆腐','Tofu, firm, prepared with calcium sulfate and magnesium chloride','soy'),
('嫩豆腐','Tofu, soft, prepared with calcium sulfate and magnesium chloride','soy'),
('黄豆（煮熟）','Soybeans, mature seeds, cooked, boiled, without salt','soy'),
('毛豆（熟）','Edamame, frozen, prepared','soy'),
('鹰嘴豆（熟）','Chickpeas (garbanzo beans, bengal gram), mature seeds, cooked, boiled, without salt','bean'),
('红腰豆（熟）','Beans, kidney, red, mature seeds, cooked, boiled, without salt','bean'),
('黑豆（熟，菜豆）','Beans, black, mature seeds, cooked, boiled, without salt','bean'),
('扁豆（熟）','Lentils, mature seeds, cooked, boiled, without salt','bean'),
('低脂牛奶（2%）','Milk, reduced fat, fluid, 2% milkfat, with added vitamin A and vitamin D','dairy'),
('全脂牛奶','Milk, whole, 3.25% milkfat, with added vitamin D','dairy'),
('原味低脂酸奶','Yogurt, plain, low fat','dairy'),
('原味全脂酸奶','Yogurt, plain, whole milk','dairy'),
('西兰花（煮熟）','Broccoli, cooked, boiled, drained, without salt','vegetable'),
('菠菜（煮熟）','Spinach, cooked, boiled, drained, without salt','vegetable'),
('大白菜（煮熟）','Cabbage, chinese (pe-tsai), cooked, boiled, drained, without salt','vegetable'),
('小白菜（煮熟）','Cabbage, chinese (pak-choi), cooked, boiled, drained, without salt','vegetable'),
('卷心菜（煮熟）','Cabbage, cooked, boiled, drained, without salt','vegetable'),
('胡萝卜（煮熟）','Carrots, cooked, boiled, drained, without salt','vegetable'),
('菜花（煮熟）','Cauliflower, cooked, boiled, drained, without salt','vegetable'),
('四季豆（煮熟）','Beans, snap, green, cooked, boiled, drained, without salt','vegetable'),
('豌豆（煮熟）','Peas, green, cooked, boiled, drained, without salt','vegetable'),
('茄子（煮熟）','Eggplant, cooked, boiled, drained, without salt','vegetable'),
('香菇（熟）','Mushrooms, shiitake, cooked, without salt','vegetable'),
('蘑菇（熟）','Mushrooms, white, cooked, boiled, drained, without salt','vegetable'),
('西葫芦（熟）','Squash, summer, zucchini, includes skin, cooked, boiled, drained, without salt','vegetable'),
('冬南瓜（熟）','Squash, winter, butternut, cooked, baked, without salt','vegetable'),
('芦笋（熟）','Asparagus, cooked, boiled, drained','vegetable'),
('番茄（生）','Tomatoes, red, ripe, raw, year round average','vegetable'),
('黄瓜（带皮生）','Cucumber, with peel, raw','vegetable'),
('生菜（生）','Lettuce, green leaf, raw','vegetable'),
('彩椒（红，生）','Peppers, sweet, red, raw','vegetable'),
('芹菜（生）','Celery, raw','vegetable'),
('洋葱（生）','Onions, raw','vegetable'),
('苹果（带皮）','Apples, raw, with skin','fruit'),
('香蕉','Bananas, raw','fruit'),
('橙子','Oranges, raw, all commercial varieties','fruit'),
('梨','Pears, raw','fruit'),
('猕猴桃','Kiwifruit, green, raw','fruit'),
('草莓','Strawberries, raw','fruit'),
('蓝莓','Blueberries, raw','fruit'),
('葡萄','Grapes, red or green (European type, such as Thompson seedless), raw','fruit'),
('西瓜','Watermelon, raw','fruit'),
('桃','Peaches, yellow, raw','fruit'),
('芒果','Mangos, raw','fruit'),
('菠萝','Pineapple, raw, all varieties','fruit'),
('木瓜','Papayas, raw','fruit'),
('牛油果','Avocados, raw, all commercial varieties','fruit'),
('核桃','Nuts, walnuts, english','nut'),
('杏仁','Nuts, almonds','nut'),
('腰果（生）','Nuts, cashew nuts, raw','nut'),
('花生（烘烤无盐）','Peanuts, all types, dry-roasted, without salt','nut'),
('芝麻','Seeds, sesame seeds, whole, dried','seed'),
('南瓜籽','Seeds, pumpkin and squash seed kernels, dried','seed'),
('葵花籽','Seeds, sunflower seed kernels, dried','seed'),
('橄榄油','Oil, olive, salad or cooking','oil'),
('菜籽油','Oil, canola','oil'),
('酱油','Soy sauce made from soy and wheat (shoyu)','seasoning'),
('食盐','Salt, table','seasoning'),
('白砂糖','Sugars, granulated','seasoning'),
('饮用水','Water, bottled, generic','water'),
]
NUTRIENTS = {'1008':'energy','1003':'protein','1004':'fat','1005':'carbs','1079':'fiber','2000':'sugar','1093':'sodium'}


def main():
    rows = list(csv.DictReader((SOURCE/'food.csv').open(encoding='utf-8')))
    chosen = []
    for name, pattern, category in SELECT:
        matches = [r for r in rows if r['description'] == pattern] or [r for r in rows if r['description'].startswith(pattern)]
        if not matches:
            print('NOT FOUND:', name, pattern)
            continue
        row = matches[0]
        allergens = {'dairy':['牛奶'],'egg':['鸡蛋'],'soy':['大豆'],'fish':['海鲜'],'nut':['坚果']}.get(category, [])
        if '花生' in name: allergens = ['花生']
        if '芝麻' in name: allergens = ['芝麻']
        if '芒果' in name: allergens = ['芒果']
        if any(x in name for x in ['面包','细面','荞麦面']): allergens.append('小麦')
        if name == '酱油': allergens = ['小麦','大豆']
        # Commercial composites lack a complete ingredient list in this source.
        complete = not any(x in name for x in ['面包','细面','荞麦面','酱油'])
        aliases = {'鸡胸肉（炖熟）':['鸡胸肉'], '牛肉（熟瘦肉参考）':['牛排','牛肉'],
                   '白米饭':['米饭'], '水煮鸡蛋':['鸡蛋'], '虾（熟）':['虾'],
                   '三文鱼（熟）':['三文鱼'], '苹果（带皮）':['苹果']}.get(name, [])
        chosen.append({'id':'usda-'+row['fdc_id'], 'name':name, 'category':category,'source':{'name':'USDA SR Legacy 2018','fdc_id':int(row['fdc_id']),'description':row['description'],'url':'https://fdc.nal.usda.gov/food-details/'+row['fdc_id']+'/nutrients'},'per_grams':100,'nutrients':{k:None for k in [*NUTRIENTS.values(),'purine']},'allergens':allergens,'ingredients_complete':complete,'aliases':aliases, 'state':'熟' if any(x in row['description'] for x in ['cooked','boiled','roasted','prepared']) else '见名称与原始描述'})
    byid = {str(x['source']['fdc_id']):x for x in chosen}
    for r in csv.DictReader((SOURCE/'food_nutrient.csv').open(encoding='utf-8')):
        if r['fdc_id'] in byid and r['nutrient_id'] in NUTRIENTS and r['amount']:
            byid[r['fdc_id']]['nutrients'][NUTRIENTS[r['nutrient_id']]] = float(r['amount'])
    dest = ROOT/'app/resources'
    dest.mkdir(parents=True, exist_ok=True)
    (dest/'foods.json').write_text(json.dumps(chosen,ensure_ascii=False,indent=2),encoding='utf-8')
    print('Saved',len(chosen),'traceable foods. Source SHA256:',hashlib.sha256((ROOT/'.tools/sr-legacy-2018.zip').read_bytes()).hexdigest())


if __name__=='__main__': main()
