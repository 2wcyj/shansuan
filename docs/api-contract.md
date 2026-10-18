# 本机API v1（已实现）

基础地址`http://127.0.0.1:18765/api`。以下路径均相对该前缀。仅本机会话；GET/session设置HttpOnly SameSite cookie并返回csrf，写操作额外带`X-CSRF-Token`。页面资源同源，无CORS放宽。默认不开放OpenAPI网页端点；结构参考`app/resources/api-schema.json`与本文。

| 动作与路径 | 输入与结果 |
| --- | --- |
| GET /session | 建立当前会话，返回csrf/app/version/data_id（非敏感目录标识） |
| GET /status | app/storage/schema/data_path |
| GET /profile | profile/draft/targets/measurements |
| PUT /profile | 完整档案及version；初次建档按适用条件生成当日计划；字段见数据字典 |
| PUT /profile/draft | values、step、version |
| GET /foods?q= | 来源与自定义食品列表；name/alias搜索 |
| POST /foods；PUT /foods/{id} | 自定义食品每100g营养、标签、来源、version、request_key |
| POST /nutrition/calculate | items含food_id/grams，返回items快照与nutrition聚合 |
| GET /records?date= | 所选日期records/nutrition/life/coverage/food_complete |
| POST /records；PUT /records/{id} | 实际date/meal/time/items/感受/version/request_key；source关联只能由计划/照片接口创建 |
| POST /records/{id}/delete | version/request_key；同步计划或照片关联状态 |
| PUT /life | date、生活字段、version/request_key；未知null |
| POST /life/water | date、amount1—2000ml、request_key；事务原子增量 |
| GET /plans/{date} | plan或null，以及blocked说明 |
| POST /plans/{date}/generate | version/request_key；保留已记餐次 |
| POST /plans/{date}/meals/{id} | version/request_key/action；replace加recipe_id，portion加factor，confirm加实际items/time；skip/resume无摄入 |
| GET /home/{date} | 实际日汇总、plan/profile/targets/feedback/blocked |
| GET /model | 固定模型name/ready |
| GET /tasks；GET /tasks/{id} | 最近20任务/单任务，包含真实状态 |
| POST /tasks/{id}/cancel | 取消结果提交；当前推理可能继续，不提供伪完成 |
| GET /analyses | 最近20照片草稿与结果 |
| POST /analyses | multipart file，不超过12MB的JPEG/PNG/WebP；加密保存后返回analysis |
| GET /photos/{id} | 鉴权后返回解密JPEG；不接受磁盘路径 |
| POST /analyses/{id}/analyze | request_key；提交串行vision任务，响应queued不等于成功 |
| PUT /analyses/{id} | items/name/ingredients/grams/food_id，version/request_key；重匹配重算；不能伪造模型证据 |
| POST /analyses/{id}/confirm | date/meal/time/version/request_key/confirmed_uncertainty；实际确认记餐，重复不新增 |
| GET /chats | 加密库中本机对话列表 |
| POST /chat | question1—1500字、可选chat_id、date、request_key；返回task/chat_id；急救与边界先返回immediate，不等待模型 |
| GET /feedback/{date} | feedback/adjustment；检查相关到期调整 |
| PUT /feedback/{date} | 反馈字段、version/request_key；同时生成可解释次日调整 |
| POST /adjustments/{date} | version、action apply/restore、request_key；依据过期返回409，复杂条件拒绝应用 |
| GET /reports?end= | 连续七日、记录覆盖、均值范围、主餐执行、生活/体重与温和建议 |
| GET /data/backups | items及warning |
| POST /data/backup | password/confirmation；经校验便携备份二进制下载 |
| POST /data/restore/check | multipart file/password；校验并返回10分钟ticket、created_at、counts、scope |
| POST /data/restore/local | name必须属于本机备份清单；返回校验ticket |
| POST /data/restore/commit | ticket/confirmation“整体替换”；当前快照成功后整体切换 |
| GET /data/export/{format} | json/csv实际下载，不加密；CSV防公式注入 |
| POST /data/delete | confirmation“删除全部个人数据”、include_backups bool；不删模型/外部文件 |
| POST /shutdown | 由正式run启动器注册，受会话和CSRF保护 |

反馈的有效枚举详见`app/backend/domain/feedback.py`；档案由`Profile`独立校验。照片items最多20项；未知匹配必须核对后才能确认。

合成午餐请求：

```json
{"date":"2026-10-01","meal":"午餐","time":"12:30","items":[{"food_id":"usda-168878","grams":150}],"satiety":3,"liking":4,"discomfort":"","request_key":"synthetic-record-request-001"}
```

实体返回id/day/version/created_at/updated_at和实际字段。创建version0，编辑传已读取版本；多数写操作携带8—160字符request_key，相同键/内容重复返回已提交结果，不同内容拒绝。草稿/档案依赖版本保护；任务取消天然幂等。恢复和删除有独立确认流程，不自动重放。

错误形如`{"error":{"code":"conflict","message":"内容已被修改，请刷新核对"}}`，不回显输入健康正文、模型原文、密钥或密码。400/422填写错误，403来源/会话/CSRF，404缺失，409版本/状态，413超限，503存储或模型不可用，504模型超时，507空间不足。失败不返回成功结果；输入由页面保留。所有响应no-store。

AI任务仅在业务结果提交成功后置succeeded。取消、档案变化、照片修订或恢复epoch变化会拦截旧结果。计划生成和便携备份为有界同步调用，页面禁用重复操作并显示处理中；AI为持久异步任务，恢复提交期间不能取消关键切换。

问答模型适配器mna-3仅返回intent、steps枚举和recipe_ids，前端获得的是根据这些实际选择、档案及记录组织的中文reply/record_note与经过过滤的食谱卡片，模型不能提供自由营养数字。该结构不是错误时的预制成功回复。
