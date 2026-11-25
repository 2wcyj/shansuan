# 膳算云端多人版实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox syntax for tracking.

**Goal:** 在不损害现有本机版和个人档案的前提下，新增可供多人安全使用的公网膳算，并先邀请约十位成年人试用。

**Architecture:** Netlify 只提供静态前端；大陆云端运行 Linux/FastAPI、PostgreSQL、私有加密附件和第一方模型。认证会话推导租户，应用与 PostgreSQL RLS 双重隔离；原 Windows DPAPI/SQLCipher 桌面模式保持单独运行。

**Tech Stack:** React 19、TypeScript、Vite、FastAPI、PostgreSQL、Alembic、SQLAlchemy async、Argon2id、AES-GCM、对象存储/KMS、Docker、Netlify。

**Spec:** `docs/cloud-multiplayer-architecture.md`

## Global Constraints

- 不读取、迁移、上传或覆盖现有 `%LOCALAPPDATA%\\MyNutritionAssistant` 数据；用户显式导入之前保持本地私有。
- 不在 Netlify Functions、Netlify 代理或第三方 AI API 传递健康资料、饮食记录或照片。
- 每个业务记录、媒体、AI 任务、备份及请求键均须有服务器侧 account_id 所属校验和 PostgreSQL RLS。
- 本地版 `create_app(data_dir)`、DPAPI、SQLCipher、桌面安装及局域网伴侣流程必须继续通过其原有测试。
- 认证使用 Argon2id；公网会话 Cookie 为 Secure、HttpOnly、SameSite=Lax；写操作校验 CSRF 和精确 Origin。
- 认证前及敏感个人信息授权前不得收集健康档案；健康内容不得写入日志。
- 每个任务先添加能证明预期行为的失败测试，确认失败后才写实现；每阶段测试通过后才进入下一阶段。
- 不创建云资源、不注册域名、不付款、不上传个人数据、不更改 DNS；这些步骤须由账户所有者在具体资源清单和费用明确后操作。

---

## 子项目 A：可移植云端运行基线

### Task A1：Docker 生产入口和健康探针

**Files:**
- Create: `deploy/cloud/Dockerfile`
- Create: `deploy/cloud/.dockerignore`
- Create: `app/backend/cloud_main.py`
- Create: `app/tests/test_cloud_boot.py`
- Modify: `requirements.lock.txt`

- [x] 先在 `test_cloud_boot.py` 写测试：`create_cloud_app` 缺少 `DATABASE_URL` 或密钥配置时启动失败；`/health/live` 不查询用户资料；`/health/ready` 只返回依赖可用布尔值，不含路径、账号或密钥。
- [x] 运行 `.venv/Scripts/python.exe -m pytest app/tests/test_cloud_boot.py -q` 并确认因模块/路由缺失失败。
- [x] 新建云端入口，导入已有 FastAPI 纯路由能力但不调用 Windows 的 `create_app`、`dpapi`、`msvcrt` 或桌面启动器。
- [x] Docker 使用固定 Python 3.12 slim 基础版本、非 root 用户、无编译缓存；锁文件安装依赖，运行 `uvicorn app.backend.cloud_main:app`。
- [x] 在 Docker 引擎中构建镜像，并验证容器 live probe 成功、无 DB 时 ready probe 返回 503。
- [x] 加入容器构建检查和健康路由测试，确认配置缺失时 fail closed。
- [x] 运行云启动测试及原有 `test_p0_crypto.py`、`test_desktop.py`、`test_mobile.py`，确认桌面路径未被云入口导入；30 项通过。加密设置 repr 测试修复后当前云启动测试 5 项通过，原有回归 26 项通过。

### Task A2：PostgreSQL schema 与迁移工具

**Files:**
- Create: `app/backend/cloud/db.py`
- Create: `app/backend/cloud/models.py`
- Create: `app/backend/cloud/migrations/env.py`
- Create: `app/backend/cloud/migrations/versions/0001_accounts_entities.py`
- Create: `app/tests/cloud/conftest.py`
- Create: `app/tests/cloud/test_cloud_schema.py`
- Modify: `requirements.lock.txt`

- [x] 建测试 PostgreSQL fixture（本地容器或 CI 服务），定义 `accounts`、`sessions`、`privacy_consents`、`entities`、`history`、`requests`、`attachments`、`entity_photos`、`links`、`tasks`、`invites`、`audit_events`。
- [x] 断言所有可含用户数据表都有 `account_id NOT NULL`、外键或复合主键、适当索引；启动测试数据库前确认迁移失败。
- [x] 使用 SQLAlchemy async engine 和 Alembic；创建独立的迁移角色与运行角色，不将超级用户凭据装入应用容器。
- [x] 迁移在 PostgreSQL 开启 `FORCE ROW LEVEL SECURITY`；应用运行角色不是表 owner、不是 superuser、无 `BYPASSRLS`。
- [x] 每个数据库 transaction 执行 `SET LOCAL app.account_id = :account_id`；RLS policy 通过该会话变量限定读写。
- [x] 测试以普通运行角色登录，未设置 account_id 时看不到数据，设置账户 A 只能看到 A，错误账户 insert/update/delete 全部拒绝。
- [x] 运行 schema、RLS 测试，并确认迁移可在空库 upgrade、downgrade 后重新 upgrade。

## 子项目 B：认证、授权与隐私同意

### Task B1：密码、会话和邀请码服务

**Files:**
- Create: `app/backend/cloud/auth.py`
- Create: `app/backend/cloud/invites.py`
- Create: `app/backend/api/cloud_auth.py`
- Create: `app/tests/cloud/test_auth.py`
- Create: `app/tests/cloud/test_invites.py`

- [x] 测试账户注册需要有效、未过期、未耗尽的邀请码；同一邀请码使用次数不可超过上限；无效邀请码不创建账户。
- [x] 测试密码数据库字段只存 Argon2id 校验值；登录错误统一提示，连续失败触发限流，登出撤销当前会话。
- [x] 实现邀请创建/核销、注册、登录、登出、当前账户、修改密码和管理员重置邀请码；令牌只保存哈希。
- [x] 会话使用至少 256 位随机数，只持久化 SHA-256 摘要，支持到期、主动撤销和账户状态封禁。
- [x] Cookie 属性依部署配置为 `Secure=True`、`HttpOnly=True`、`SameSite=Lax`，设置合适 Path 和有限 Max-Age；本地测试允许专用 test settings。
- [x] 登录和邀请路由按 IP 与账户限速；响应和日志不得区分某邮箱是否注册。
- [x] 为忘记密码发送一次性、短时、单次使用重置链接；token 仅存哈希，密码重置后撤销该账户全部会话。SMTP/provider 通过 `Mailer` adapter 注入，测试使用 fake mailer，生产只传递邮箱和短期重置链接。
- [x] 运行认证与邀请码专项测试，再运行应用安全中间件测试。

### Task B2：敏感信息单独授权和隐私权接口

**Files:**
- Create: `app/backend/cloud/consent.py`
- Create: `app/backend/api/cloud_privacy.py`
- Create: `app/tests/cloud/test_consent_privacy.py`
- Create: `app/frontend/src/cloud/Consent.tsx`
- Create: `docs/privacy-notice-draft.md`

- [ ] 测试没有当前版本的健康信息单独授权时，健康档案、记录、照片、问答个人上下文的写接口返回 428，普通注册/登录仍可用。
- [ ] 测试撤回授权阻止新的健康处理，导出与删除入口仍可访问。
- [x] 记录授权文本版本、同意时间、撤回时间及用户代理的 HMAC 摘要；不得将健康内容放入同意行。
- [x] 前端提供独立的敏感信息授权选框和服务端隐私草案全文，默认不勾选；用户拒绝可保留会话后退出，也可使用下方账户数据权利入口。
- [x] 提供重新验证密码的账户 JSON 导出接口；包含账户邮箱、解密后当前业务实体、历史版本、删除墓碑与授权历史，不导出凭据或密钥。检测到账户存在云附件时拒绝生成不完整导出（等待云对象存储导出能力）。密码复验按账户限流（15分钟12次），超限返回429。
- [x] 提供重新验证密码及明确确认语的永久删除接口；数据库函数限制只能删除本人账户、保护最后一个管理员，PostgreSQL 外键级联清除账户、会话、同意、实体、历史和密钥。附件尚未实现，若发现附件则安全拒绝；成功响应说明云备份尚未配置及其上线前保留期限事项。
- [x] 云端登录/授权页面已接入数据导出下载与账户删除表单；用户撤回健康信息授权后仍可行使上述权利。
- [x] 建立隐私说明开发草案，列明数据类别、目的、计划存储地、权利、第三方边界和上线前待补信息；上线前仍需负责人法律审查。
- [x] 运行隐私同意专项测试和前端类型检查；隐私同意端到端浏览器测试覆盖默认未勾选、同意与撤回。

## 子项目 C：租户隔离业务存储与现有规则复用

### Task C1：请求级账户上下文与数据加密

**Files:**
- Create: `app/backend/cloud/context.py`
- Create: `app/backend/cloud/crypto.py`
- Create: `app/backend/cloud/repository.py`
- Create: `app/tests/cloud/test_tenant_repository.py`
- Create: `app/tests/cloud/test_cloud_crypto.py`

- [x] 测试 repository 无认证 account_id 时拒绝操作；跨账户 get/list/update/delete 均不可访问。
- [x] 测试每账户 DEK 对 payload AES-256-GCM 加解密成功；篡改密文、错误账户 key 和关联账户绑定失败关闭。
  - [x] 实现阿里云 KMS Encrypt/Decrypt 包封每账户 DEK，账户 UUID 进入 KMS encryption context；强制大陆地域、具体 CMK ID 和官方 credential chain，SDK 失败统一返回无密钥细节的服务错误。
  - [x] 生产/预发布必须配置 KMS，服务启动与 ready probe 以随机合成账户密钥验证 KMS 可用；KMS 故障令服务启动失败或 ready=503；KMS SDK 同步网络调用放入线程，不阻塞异步 API。
  - [x] 加密仓储只在首次创建账户密钥时调用 KMS Encrypt，之后仅解封已存密钥；现有 wrapped key 在服务重启后可读取。
  - [x] KMS SDK 及传递依赖按版本锁定至云镜像；增加不含凭据的 `.env.example`。真实云 KMS/RAM 资源未配置，不能称为生产加密已验收。
- [x] 实现请求级 `TenantRepository`：方法只接受实体 kind/id/body，不接受客户端 account_id；account_id 只来自请求租户上下文。
- [x] 实体 body、历史正文和幂等结果加密；kind、日期和对象 id 保留最小索引元数据并在隐私说明中解释。幂等结果当前封存在加密的 `mutation_request` 实体中；独立 `requests` 表仍未接入业务 API，禁止新路由在未加密结果值的情况下使用它。
- [x] 每次独立数据库事务以 `SET LOCAL app.account_id` 设置上下文，事务结束即清理；并验证异步任务租户上下文不串户。
- [x] 执行加密、账户隔离、RLS 和本机 `Store` 回归测试。真实连接池交错读写回归仍需加强。

### C1 机密性回归补充（2026-10-22）

- 新增真实 PostgreSQL 集成测试，使用合成敏感字符串验证实体正文、历史快照与幂等操作响应均以密文写入；数据库直读也无法在这些密文列中搜索到明文标记。
- `pytest app/tests/cloud/test_tenant_repository.py -q --tb=short`：3 项通过。该检查证明当前落库路径，不代表真实阿里云 KMS 或生产密钥部署已验收。

### 早期执行记录（2026-10-21，最新状态见下方 C2 接入进展）

- 隐私授权后端已实现版本核验、授权状态、撤回和健康写入依赖；用户代理只保存 HMAC 摘要。草案已创建，但前端授权 UI、导出/删除工作流及完整业务路由 consent gate 仍未完成。
- C1 基础层已实现：请求局部租户上下文、AES-256-GCM、KMS adapter 接口、账户包封密钥记录表（迁移 0003）及通用加密实体 CRUD 仓储。真实云 KMS provider、连接池复用回归和现有业务 API 接入仍待完成。
- 全量回归 `pytest app/tests -q`：132 项通过；本地 Docker 镜像构建成功，容器探针实测 `live=ok`、无 DB 时 `ready=503`。前端 `pnpm run build` 通过。
- 全量回归发现桌面离线安装锁文件误混入云端依赖和旧交付清单哈希过期；已将云依赖隔离至独立容器锁文件并修复配方资源清单。修复后两项原失败用例均单独通过。
- 浏览器测试通过登录隔离、同意默认未勾选、明确同意及撤回；云端个人资料业务 UI 尚不可用。
- 云端新增 `/api/profile` 读写与 `/api/profile/draft`：复用现有 Profile 校验与目标计算，已验证同意拦截、双账户隔离、草稿隔离、版本冲突和无效输入。档案与测量写入共用事务；模拟测量故障后验证档案也回滚，修改前档案保存为加密历史。
- 新增单连接池并发账户交错回归，验证 RLS 上下文在事务结束及连接归还后清除。生产 KMS 尚未配置，业务仓储只在测试注入；档案更改后的计划复核/首次生成尚未接入，不能据此宣称个人档案云端业务兼容已完整完成。

### C2 接入进展（2026-10-21 更新）

- 新增请求内纯内存 `DomainStore` 适配器：在账户事务锁内加载该账户密文，复用原同步业务规则，原子提交加密实体、历史、请求幂等结果与关联；不创建 SQLCipher/本机文件，不把用户仓储放入可变全局账户状态。
- 档案保存已改为调用原 `save_profile`，首次生成四餐、测量保存与待执行计划复核均复用原函数。之前“档案与计划关联未接入”的限制已由此项取代。
- 已有云端路由：档案/草稿、计划读取和餐次变更、实际记录列表/创建/编辑/删除、饮水、反馈读取/保存、七天报告。专项覆盖计划不计入实际摄入、营养计算、重复记餐去重、跨账户编辑删除拒绝、餐次确认、反馈隔离、档案更新后旧计划不能直接执行。
- `plans.change` 的本机 SQL link 写入抽取为存储方法；桌面 Store 仍执行同一 SQL，云适配器只写当前账户加密关联实体。反馈 JSON 编码移至跨平台模块，避免 Linux 导入本机 SQLCipher。
- 删除使用加密墓碑保留版本与历史，普通列表不展示；账户彻底删除仍需后续专用隐私删除流程，不能将墓碑视为数据擦除。
- 云端 API 已接入档案/草稿、首页、食物与营养计算、饮食计划、记录增删改、饮水、睡眠/生活记录、反馈、七天报告，以及产品目录/详情/设置/加入计划/取消计划/确认食用。产品计划与实际记录分开；只有已核实商品经用户确认食用才按标签和分量计入。每个写操作沿用本机领域规则，并经加密租户仓储提交。
- 产品计划端点由真实 PostgreSQL 双账户集成测试先失败（缺少路由、404），再实现并验证通过；覆盖加入/取消、幂等重放、跨账户访问拒绝、未确认不记餐、确认后营养统计及计划重复消费拒绝。
- 撤回敏感信息授权后的已启用健康 API 清单有集成回归：档案、首页、营养、生活、反馈、报告、计划、记录与产品读写全部返回 428；登录与隐私授权状态继续可访问。照片、问答与 AI 个人上下文路由尚未建立，不能据此视为其功能已完成。
- 新增真实 PostgreSQL 共享连接池（最多三个连接）并发账户交错领域测试，覆盖账户锁、幂等重放、删除墓碑/版本历史、删除后重建、数据不串户及连接归还后 RLS session variable 清理；原有仓储测试另覆盖单连接池复用。
- 最终串行全项目回归 `pytest app/tests -q --tb=short`：137 项通过（252.86 秒）；云端专项 33 项通过。一次并行运行两套全量测试时，本机共享模型进程出现两个环境竞争失败；原用例单独串行 2 项通过，随后无并行套件的完整重跑全部通过，没有跳过或降低断言。保留一项 Starlette/anyio 弃用警告。云端前端三项浏览器/API host 测试已通过，Vite 生产构建通过。Docker 镜像最新代码已构建，并实测容器 live=ok、数据库不可用时 ready=503、无启动错误日志。
- 当前总体仍不可用于真实健康资料或朋友试用：生产 KMS provider 和启动 fail-closed 校验、账户存在附件时的完整对象导出/删除协调、照片私有存储、持久 AI worker/模型、完整云端业务前端、云端备份导入/恢复、正式备份保留与恢复、运营监控和安全审查均未完成。尚未创建云资源、设置 DNS 或部署公网；现有本机数据没有迁移。

### B2 账户权利增量（2026-10-21）

- 新增数据库迁移 `0004_account_privacy`，受限函数只允许当前账户删除本人，保护最后一个管理员；账户级锁与管理员删除锁避免本流程自身并发交错。
- 新增 `POST /api/privacy/export`：密码复验、CSRF、账户限流；含当前业务资料、加密历史解密副本、删除墓碑、同意记录与邮箱，不含凭据/密钥。浏览器下载的是未加密 JSON，页面有明确提示。
- 新增 `DELETE /api/privacy/account`：密码复验及完整确认语；级联删除账户相关数据库记录、密钥及会话，清除 Cookie；其他账户不受影响。检测到账户附件时先拒绝，直到对象清理流程完成。
- 云端授权页无论是否同意健康处理，都保留账户数据权利表单。实际浏览器测试验证撤回后仍可导出、下载文件名和确认删除后返回登录。
- 最终全量 `pytest app/tests -q --tb=short`：139 项通过（264.79 秒），保留一项 Starlette/anyio 弃用警告。前端 `pnpm run build`、三个云端浏览器/API配置专项、最新 Docker 镜像构建均通过。含附件的导出/删除、云备份生命周期与完整生产验证仍未完成，不代表 B2 全部上线条件已经满足。

### B2 安全复审修复（2026-10-21）

- 数据导出和账户删除改为单个受保护事务：账户域锁→账户行锁→当前会话行锁→密码复验→数据操作；限流单独提交，失败不回滚计数。导出的授权记录、附件检查、实体和历史共享事务，不再在账户删除后返回空成功副本。
- 新增迁移 `0005_privacy_lock`：受限数据库函数只锁定当前账户的凭据；变更/重置密码也先取得账户行锁，保持账户→令牌/会话的锁顺序。部署新代码前必须升级数据库到此版本。
- 登录在密码验证后、创建会话前再次取得账户行锁，核验当前密码哈希与账户状态；防止旧密码验证与重置交错后创建新会话。
- 隐私操作与密码重置在等待锁后，使用数据库实际时间 `clock_timestamp()` 检查凭据有效期；隐私操作还覆盖密码验证耗时。不能使用固定在事务起点的 `now()` 判断等待后的到期状态。
- 新增真实 PostgreSQL 并发回归：复验期间重置等待；等待导出期间删除、重置、登出后拒绝；旧密码登录不能越过密码重置；锁等待期间过期的会话和重置令牌拒绝。新增缺陷均先观察测试失败，再实现修复。
- 实际浏览器测试检查删除前如实提示“云端备份尚未配置”，不承诺尚未实现的保留与清理流程。复审未发现本轮修复的重要遗漏。
- 最新代码完整回归 `pytest app/tests -q --tb=short`：147 项通过（281.31 秒），保留一项 Starlette/anyio 弃用警告。前端 TypeScript/Vite 生产构建及三个云端浏览器/API配置专项通过；最新 Docker 镜像构建成功，实际容器 `live=ok`、数据库不可用时 `ready=503`。测试使用一次性本机数据库及合成资料；未提交 Git、上传个人数据或部署公网。此结果只代表本轮安全增量，完整云端上线阻碍仍见上方 C2 当前状态。

### Task C2：按 API 模块接入租户 repository

**Files:**
- Modify: `app/backend/api/profile.py`
- Modify: `app/backend/api/records.py`
- Modify: `app/backend/api/plans.py`
- Modify: `app/backend/api/feedback.py`
- Modify: `app/backend/api/products.py`
- Modify: `app/backend/api/ai.py`
- Create: `app/backend/cloud/dependencies.py`
- Create: `app/tests/cloud/test_tenant_api_isolation.py`

- [ ] 先写 API 双账户隔离集成测试：A 创建档案/记录/产品/计划后，B 的列表为空且逐 ID 读取、更新、删除都不可访问；先运行确认失败。
- [ ] 增加 FastAPI dependency：读取已验证会话、检查 consent、创建请求级 tenant repository；严禁在 `app.state` 放置当前用户可变 repository。
- [ ] 为 profile/records 接入 repository 后运行其 API 兼容测试；再逐个接入 plans/feedback/products，保持 DTO、营养计算、安全筛选和写入语义一致。
- [ ] 以不同 request coroutine 并发交错读写两个账户，断言任何记录、历史、幂等结果不串户。
- [ ] 任务、照片和产品附件暂留原有路由但在未迁移前返回清晰的功能未启用状态，不允许回落到本机 Store 或公共共享数据。
- [ ] 运行全部本机后端测试和新的云 API 双账户隔离测试。

### Task C3：显式本地便携备份导入

**Files:**
- Create: `app/backend/cloud/import_backup.py`
- Create: `app/backend/api/cloud_import.py`
- Create: `app/tests/cloud/test_cloud_backup_import.py`
- Modify: `app/frontend/src/cloud/AccountData.tsx`

- [ ] 测试导入必须有已登录账户、当前敏感信息授权和正确 `.mnab` 密码；密码错误/损坏包不产生任何数据变更。
- [ ] 测试预览返回对象数量与日期摘要，不返回健康正文；用户第二次明确确认后才原子写入当前账户。
- [ ] 导入解析采用现有 Backups 格式校验，确认附件、版本和数据约束；导入不调用或修改 Windows 本地数据目录。
- [ ] 数据导入冲突采用“仅导入到空的云端个人空间”策略，已存在数据时拒绝并指引用户，不自动合并或覆盖。
- [ ] 运行备份导入与回滚测试，并将导入文件在处理后释放临时副本。

## 子项目 D：照片、任务队列和云端模型

### Task D1：私有对象存储与照片授权

**Files:**
- Create: `app/backend/cloud/object_store.py`
- Create: `app/backend/api/cloud_photos.py`
- Create: `app/tests/cloud/test_photo_tenant_isolation.py`
- Modify: `app/backend/cloud/models.py`

- [ ] 测试图片上传格式、MIME、最大 12 MB、尺寸、随机 key、账户关联及授权要求；A 的照片 ID 不能由 B 读取/删除。
- [ ] 使用随机对象 key，将照片内容先用账户 DEK AEAD 加密，再上传私有 OSS bucket；不公开 ACL，不把原文件名作为 key。
- [ ] 下载经 API 鉴权后代理解密或返回有效期不超过 60 秒的只读签名 URL；不能由客户端指定 bucket/key。
- [ ] 删除账户/照片时同时撤销记录关联与对象；上传/模型失败时清除孤儿对象。
- [ ] 日志只记录内部随机附件 ID，不记录 URL token、文件名、图片或模型 prompt。
- [ ] 用 fake object store 测试后运行 Linux 兼容和本机照片回归。

### Task D2：持久 AI 任务和第一方推理

**Files:**
- Create: `app/backend/cloud/task_queue.py`
- Create: `app/backend/worker.py`
- Create: `deploy/cloud/worker.Dockerfile`
- Create: `app/tests/cloud/test_cloud_tasks.py`
- Modify: `app/backend/api/ai.py`

- [ ] 测试任务携带 account_id；A 不能读写 B 的任务状态/结果；取消、过期和重试遵守所有者和幂等键。
- [ ] 将云端任务写 PostgreSQL 持久队列；worker 使用独立低权限数据库角色，只访问租户 context 下的任务，不再依赖进程内队列。
- [ ] 模型运行端口仅绑定云私网；关闭自动云功能、外部 telemetry 和第三方 model fallback；worker 在无模型时返回明确重试/失败状态。
- [ ] 图片照片分析和问答通过账户授权解密必要上下文，执行过敏/疾病规则后生成建议；模型不能覆盖规则引擎判断。
- [ ] 完成后删除任务 prompt/中间图片明文或设置明确短 TTL；保留用户实际查看所需的受保护结果。
- [ ] 用假模型验收 owner/重试和医学安全测试；部署前做模型性能与成本基准，未过容量门槛不开放 AI 公测。

## 子项目 E：Netlify 前端与上线文件

### Task E1：前端 API endpoint 和会话

**Files:**
- Modify: `app/frontend/src/api.ts`
- Modify: `app/frontend/vite.config.ts`
- Modify: `app/frontend/index.html`
- Create: `app/frontend/netlify.toml`
- Create: `app/tests/cloud/frontend-session.cjs`
- Create: `docs/netlify-deployment.md`

- [ ] 测试 `VITE_API_BASE_URL` 为空时使用本地同源 `/api`，设置时所有 `/api/*` 请求使用配置 API origin 并 `credentials:'include'`；连接失败保留可重试错误。
- [ ] 精确处理图片、备份、下载的跨域 credential；不使用 `Access-Control-Allow-Origin:*`，不在前端保存 password、session token 或云 KMS 密钥。
- [ ] `netlify.toml` 构建目录 `app/frontend`、命令 `corepack pnpm install --frozen-lockfile && corepack pnpm run build`、发布 `dist`，SPA 回退到 `/index.html`。
- [ ] CSP `connect-src` 只加入生产 API origin；预览环境只允许预览 API，不允许连生产数据。
- [ ] 本地 API 同源开发 proxy 保持原样。通过 Playwright 使用 fake API 断言 cookie credentials、API host 与页面回退。
- [ ] 执行 TypeScript、Vite build、前端会话专项测试；Netlify 部署前检查 build log 不包含 env secrets。

### E1 业务前端接入增量（2026-10-22）

- `App.tsx` 在云端模式经过账户和单独同意门禁后挂载复用业务组件；档案向导的草稿写入、个人空间文案及 API 会话分别按云端/本机模式处理。云端不会运行本机模型状态轮询、手动本机恢复点或 DPAPI 隐私表单；未接入的云照片和问答入口显示未启用。
- 云端会话初始化改为 `/api/auth/session`，本机保留 `/api/session`。退出、撤回、删除与重新登录清理 Query 缓存和 API 内存会话，API 401/428 关闭健康业务界面；错误正文兼容云端 `detail` 和本机 `error` 格式。
- 新浏览器断言先因缺少获准后档案页面而失败，接入后通过；覆盖默认不同意、授权前不访问档案、获准进入档案、CSRF 草稿保存、撤回卸载、同浏览器第二账户无旧草稿、服务端授权失效、手机菜单不调用本机备份和横向溢出。
- 使用真实 Edge、合成云端 API 验证：`cloud-api-config.cjs`、`cloud-frontend-browser.cjs`、`cloud-consent-browser.cjs` 均通过。原本机 `mobile-layout-browser.cjs` 的 7 组检查通过。最新 TypeScript/Vite 生产构建通过。截图保存在系统临时目录，未提交真实健康资料或部署云服务。
- 前端改动前最后一次全后端回归为 158 项通过；本轮未改后端。真实云 API 与业务页面完整联调、产品附件、照片/AI、备份导入恢复、线上域名与 Cookie 验收仍需继续，不将本轮视为 E1 或整体发布验收完成。

### Task E2：公开注册准备和运营安全

**Files:**
- Create: `docs/production-readiness.md`
- Create: `deploy/cloud/env.example`
- Create: `deploy/cloud/observability.md`
- Modify: `README.md`

- [ ] 生产 readiness 文档列出实际负责人逐项设置的 DATABASE_URL、KMS key id、SESSION secret、CORS origins、object bucket、模型内网地址、mail provider、invite policy 和 health endpoint；example 只写非秘密占位示例。
- [ ] 加入结构化脱敏日志和指标白名单，测试通过故意触发照片、AI、profile 错误后日志无字段值、prompt、email、secret、cookie 和图片数据。
- [ ] 创建限流/容量/数据库连接上限/备份保留/恢复时限/告警 runbook；设置账户/单日 AI 使用上限和上传配额。
- [ ] 文档加入隐私政策、用户协议、敏感个人信息单独同意、成人试用范围、客服/权利申请入口；文字标为上线前法律审阅草案。
- [ ] 更新 README 明确本机和云端为两种运行模式、云端版本仍未发布，不能提供生产 URL 假装上线。
- [ ] 检查容器安全扫描、依赖漏洞扫描、secret scan、全套本机测试和云端集成测试。

## 子项目 F：实际部署和邀请测试（需要用户账号操作）

### Task F1：测试环境连接

**Files:** 云控制台由用户账户创建；仓库只存部署文档和非敏感设置。

- [ ] 用户本人创建大陆云资源：容器主机/数据库/私有对象存储/KMS/域名及证书；逐项确认账单、区域、最低公网端口和备份保留成本后再创建。
- [ ] 用户本人完成域名实名、网站备案和适用安全备案；备案通过前不指向公网生产站点。
- [ ] 在 Netlify 用户账号导入指定 GitHub 仓库，设置 Base directory、Build command、Publish directory 和 `VITE_API_BASE_URL`；Secrets 仅写 Netlify/云控制台，不进 Git。
- [ ] 配置自定义同注册域名前端/API 子域名（例如 `app.example.cn`、`api.example.cn`）；Netlify 默认域名只能用于静态预览，不能作为 SameSite=Lax Cookie 的生产登录验收域。
- [ ] 先部署无真实资料的 staging；按 DNS/TLS/CORS/Cookie/CSP/Android viewport 跑端到端检查，测试数据使用合成账户。
- [ ] 从中国大陆不同移动网络检查 Netlify 首页和 API 可访问性；失败时静态资源改放大陆备案静态服务，不把 API 转给 Netlify 代理。

### Task F2：备份恢复和十人封闭试用

- [ ] 使用两套测试账户完成全模块双账户读写、照片、AI、反馈、产品、导出、删除、恢复演练和 RLS 直接查询检查。
- [ ] 验证加密备份可跨进程/跨主机解密；模拟数据库/对象存储恢复，记录操作时间和结果。
- [ ] 用户确认邀请名册与隐私告知后，管理员只发一次性邀请码给约十名成年人；不在公开源码、日志或聊天中留存实际邀请码。
- [ ] 试用期收集错误类型/性能指标，不收集健康内容分析；设定安全事件联络与停止服务开关。
- [ ] 达到 architecture spec 中上线验收门槛后，由用户本人确认开放注册、域名与 Netlify production promotion。

## 验收执行命令

```powershell
.venv\Scripts\python.exe -m pytest app/tests -q
.venv\Scripts\python.exe -m pytest app/tests/cloud -q
cd app/frontend
pnpm install --frozen-lockfile
pnpm run build
```

当前云端集成测试 fixture 自动建立一次性本机 Docker PostgreSQL 容器（数据库固定为 `shansuan_test`），使用随机凭据和普通运行角色，结束后删除测试容器；不会从环境读取生产数据库进行测试。`DOCKER_CLI` 可指定 Docker 可执行文件。不要同时运行两套全量测试：原有本机模型集成测试会共用并启停专用模型进程，应串行执行。生产凭据不得用于自动化测试。
