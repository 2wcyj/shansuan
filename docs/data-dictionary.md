# 数据字典 v1（实际实现）

SQLCipher schema1。通用实体表`entities`：kind、id、day（所选本地自然日或null）、body（JSON）、version（从1递增）、created_at/updated_at（含时区）。数据库页与日志为密文，JSON正文不是独立明文文件。

| kind | 数据与约束 |
| --- | --- |
| profile | 单例self；sex男/女/未说明；age1—110，height50—250cm，weight10—350kg，waist20—250cm、body_fat2—70%可空；sleep_hours0—24、exercise_weekly0—21、activity久坐/轻度/中度/高强度、lifestyle；goals及属于其中的primary_goal |
| profile（健康） | health_status/allergy_status：未填写/明确无/有，只有有可且必须含标签；conditions、allergens、allergy_notes、intolerances、physiology普通/孕期/哺乳期/待确认；professional_notes/energy_min/energy_max/protein；restrictions |
| profile（偏好） | likes/dislikes/excluded/tastes/diet/methods/excluded_methods/forms；budget可空1—2000元、prep_minutes可空0—240、cooking便利程度、measurement_date |
| draft | 单例onboarding，values、step0—5；允许不完整，不能当作正式档案 |
| measurement | id为日期-指标，metric weight/waist/body_fat、value、source（生活编辑可追溯），保留不同日期 |
| food | 自定义食品，以custom-开头；name、state、per_grams100、nutrients、source对象、allergens、ingredients_complete、category、aliases |
| record | day、meal早餐/午餐/晚餐/加餐、time HH:MM、items来源快照、nutrition聚合；source manual/plan/photo、plan_id/meal_id/analysis_id；satiety/liking1—5可空、discomfort文字 |
| life | id为日期；water_ml0—12000、sleep_hours0—24、exercise_minutes0—1440、身体测量可空、feeling、food_complete（本人确认） |
| plan | id为日期；profile_version、rule_version、needs_review、manual、targets、meals、nutrition、adjustment；meal状态pending/recorded/skipped，record_ids；recommendation及alternatives含配料/克数/做法/成本/时间/来源 |
| analysis | photo_id、status draft/analyzed/revised/confirmed、items（名称/配料/克数/匹配/两类定性把握/营养snapshot）、risks、advice、uncertainty、meta模型与提示版本、record_id |
| chat | title、turns；每轮role user/assistant、content，assistant.result含reply/record_note/recipes/citations/meta |
| feedback | 按日期；adherence、hunger、taste、difficulty、energy均含未填；discomfort_status未填/无/有、symptoms、binge可空bool、special、temporary_goal、suspect_food_ids、profile_version |
| adjustment | 日期及target_date；输入signature、inputs、before、proposal、changes、impact、result_plan_version、status applied/unchanged/pending_review/confirmed/restored、limitations、rule_version |
| task | kind vision/chat，status queued/running/succeeded/failed/cancelled/interrupted；payload/result/error；健康上下文仅在加密库，不进入运行日志 |

辅助表：`history`保存旧实体版本；`requests`保存幂等键/内容摘要/结果；`attachments`保存照片id、sha256、明文字节数（表本身加密）；`entity_photos`、`links`通过外键约束来源/目标，级联清理关联。

每项营养单位：energy kcal；protein/fat/carbs/fiber/sugar g；sodium/purine mg。基础食品每100g，实际items为可食部克数（0.1—5000g，单记录1—40项）。糖是总糖，不能当游离糖；嘌呤无来源则null。

聚合示例：`{"known":260,"unknown":1,"complete":false,"total":null,"unit":"kcal","label":"热量"}` 表示有已知部分和1项未知，不能作为完整总摄入；无记录known/total为null，真实0仍是已知。`total`只有全部条目已知时返回数值。没有记录不等于0摄入。

创建version0；编辑传当前version，陈旧409。`request_key`8—160字符，相同内容重试返回原结果、不同内容同键拒绝。营养来源更新不静默改写旧snapshot。恢复使用新数据代epoch拒绝旧AI写入。
