# 食物与规则来源

基础数据采用美国农业部 FoodData Central，SR Legacy 2018-04 CSV。

- 官方下载：https://fdc.nal.usda.gov/download-datasets/
- 文件：https://fdc.nal.usda.gov/fdc-datasets/FoodData_Central_sr_legacy_food_csv_2018-04.zip
- 使用说明：https://fdc.nal.usda.gov/data-documentation.html （USDA数据为公共领域；使用时标注来源）。
- 所有条目保留FDC编号、原始英文描述和公开详情链接。中文名是描述翻译，不表示某一中国品牌。
- 每100g可食部分；熟食只匹配熟食条目，原料生重不直接当作熟食。
- 原始表缺失的营养值为null，包括未收录的嘌呤；不能通过语言模型补造。
- 数据对应参考食物，家庭或外卖的油盐、品种、烹饪损耗可有差异，界面统一标注估算。
- 配方分量由本应用设计，营养由所选基础食物按重量累计；调料显式计入。价格只是作者整理的预算参考，不是市场实时价格。
- 自定义/包装标签数据标记为用户填写，不混作USDA数据。
- 本次原始ZIP SHA256：`b80817294b8850530aaedf2e515c02593b1824f763a0ff356e5c2081643e6fd0`；已选82条。复现脚本：`app/scripts/build_food_data.py`。

目标参考拟采用Mifflin-St Jeor成人静息代谢估算（Am J Clin Nutr 1990;51:241–247，DOI:10.1093/ajcn/51.2.241）；活动系数为生活强度粗估，并显示适用边界。成年健康人蛋白参考起点为0.8g/kg（National Academies, DRI 2005），训练目标使用ACSM 2016运动营养立场建议范围，具体实现须记录所选值，避免医学人群套用。

专业限制由用户记录，应用只执行明确可核对的限制。糖尿病、肾病、孕哺、未成年人、术后等不自动套用普通减脂/增肌目标。疾病标签不能替代专业处方。
