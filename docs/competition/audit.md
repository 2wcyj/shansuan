# 现状审计矩阵

- 审计日期：2026-11-25
- 项目路径：`C:\Users\hp\Desktop\食品`
- 分支/远端：`main` → `github.com/2678381975-dot/shansuan`
- 方法：读取 README、PRD、`docs/`、后端源码、迁移、前端入口与既有测试；运行本环境可执行的测试。
- 重要边界：**未收到《赛题一作品信息收集表》**，因此无法核对申请表字段与"7 个技术模块"原文；下表按实施方案第四章 A 类 12 项能力映射，待收到信息表后补齐对照列。

状态取值：

| 状态 | 含义 |
| --- | --- |
| 已实现·已验证 | 有可复现测试或真实运行证据 |
| 已实现·待验证 | 代码存在，但本环境未能跑通对应证据 |
| 部分实现 | 只覆盖了能力的一部分 |
| 未实现 | 无代码或数据 |
| 依赖授权 | 需用户账号、付费资源或公开发布 |

## 1 能力矩阵

| 能力项 | 源码位置 | 现有证据 | 实际状态 | 行动 |
| --- | --- | --- | --- | --- |
| 1 云端网页（手机/电脑浏览器） | `app/frontend/src/`、`cloudApiConfig.ts`、`app/backend/cloud_main.py` | `app/frontend/dist` 已构建；`app/tests/cloud-frontend-browser.cjs` 存在但本环境无法运行（loopback 受限） | 已实现·待验证 | 在正常网络环境跑浏览器脚本；阶段 6 |
| 2 账户隔离、同意与隐私操作 | `cloud/auth.py`、`api/cloud_auth.py`、`api/cloud_privacy.py`、迁移 0001/0002 | 历史记录 33 项云端专项通过；本环境 PostgreSQL 集成测试需 Docker | 已实现·待验证 | 启动 Docker 后回归；阶段 2 |
| 3 个人档案、目标、过敏原、偏好 | `domain/profile.py`、`api/cloud_profile.py` | 同上 | 已实现·待验证 | 阶段 2/3 |
| 4 三餐与加餐建议、替代、分量 | `domain/plans.py`、`frontend/src/Meals.tsx` | 历史本机 95 项后端测试记录；未能复跑 | 已实现·待验证 | 阶段 3 |
| 5 普通食物与已核实蛋白产品推荐 | `domain/food.py`、`domain/products.py`、`resources/foods.json` | 本机测试记录；产品目录含 6 项待核实概念产品 | 已实现·待验证 | 阶段 3；补齐未核实产品负向测试 |
| 6 实际饮食/饮水/睡眠/运动/体重/反馈 | `domain/records.py`、`domain/feedback.py` | 同上 | 已实现·待验证 | 阶段 3 |
| 7 照片分析、人工修订、确认记餐 | `cloud/conversation.py`、`api/cloud_ai.py`、`api/cloud_photos.py`、`cloud/photos.py` | 云端新增 `/api/analyses/{id}/recognize`，调用华为云视觉模型；`test_cloud_ai.py` 校验 schema、分量范围与置信度默认低 | 已实现·未用真实模型验证 | 阶段 7 用真实 API 验收 |
| 8 结合个人条件与记录的 AI 问答 | `cloud/conversation.py`、`api/cloud_ai.py`、`ai/safety.py` | 云端新增 `/api/chat`；模型只能选意图/步骤/已筛选食谱，数字由程序渲染；急救与过敏规则短路 | 已实现·未用真实模型验证 | 阶段 7 |
| 8 结合个人条件与记录的 AI 问答 | `ai/`（本地 Ollama） | `cloud_main.py` 未 include AI 路由 | 部分实现 | 阶段 4 |
| 9 血压与静息心率记录及趋势 | `domain/records.py`（`vital` 实体）、`api/records.py`、`api/cloud_business.py`、`frontend/src/Vitals.tsx`、`Report.tsx` | `test_vitals.py` 11 项通过（成组校验、同日多次不覆盖、极端值保留并提示、版本冲突、删除、报告含体征）；前端 `tsc --noEmit` 与 `vite build` 通过 | 已实现·已验证（domain/构建）；浏览器流程待环境 | 阶段 6 补浏览器回归 |
| 10 七天与三十天报告 | `domain/reports.py`、`api/feedback.py`、`api/cloud_business.py`、`frontend/src/Report.tsx` | `test_reports_window.py` 8 项通过（7/30 窗口、空日不补零、非法窗口拒绝）；前端 `tsc -b` 与 `vite build` 通过 | 已实现·已验证（domain/构建）；浏览器流程待环境 | 阶段 6 补浏览器回归 |
| 11 华为云适配与部署 | `cloud/kms.py`、`object_store.py`、`redis_store.py`、`deploy/cloud/`、`deploy/huawei/` | 合成单测：KMS/OBS 7 项、Redis 6 项中部分因环境失败；无真实云探测 | 部分实现·依赖授权 | 阶段 2/7；真实资源由用户创建 |
| 12 CodeArts/Skills 证据与官方 Word | `docs/competition/` | 本目录；无 Word、无信息收集表 | 进行中 | 阶段 8 |

## 2 赛事必需项

| 必需项 | 状态 | 说明 |
| --- | --- | --- |
| 使用华为云码道 CodeArts | 已使用 | 本次改造在本会话内完成，证据见 `codearts-evidence.md` |
| 关联 RDS/Redis 等华为云服务 | 代码就绪，未开通 | 需用户实名与付费确认 |
| 华为云部署 | 未部署 | 交付可部署包，见 `deployment.md` |
| 报名（截止 2026-11-30 23:59:59） | 未确认 | 用户操作 |
| 初赛模板 1 Word（截止 2026-12-15 18:00） | 未生成 | 阶段 8 |
| 开源（GitHub） | 仓库已存在 | 本次改动尚未提交，待用户确认 |

## 3 阻碍与环境限制

1. 沙箱禁止 loopback：`OSError: [WinError 10051]`，导致应用无法启动、`TestClient` 测试与 `asyncio.run` 测试失败、截图脚本无法执行。
2. Docker 未运行：`test_kms.py::test_repository_uses_existing_wrapped_key_without_new_kms_encrypt` 等 PostgreSQL 集成测试报错。
3. 无华为云账号：KMS/OBS/DCS/RDS 真实探测与费用确认无法进行。
4. 未提供信息收集表与团队信息：申请表只能延后填写。

以上均为**环境或授权阻碍**，不是代码缺陷；不得据此宣称全量通过。

## 4 结论

- 本机版业务闭环和云端账户/隔离框架已存在，但云端 AI、体征、30 天报告仍未实现。
- 华为云适配已完成编码与合成单元测试，**没有真实云验证**。
- 材料中凡是"已完成"的口吻，仅限本矩阵"已实现·已验证"的行；其余必须写成开发中、规划或依赖授权。