# 膳算网页内测 A：联网环境与账号基础 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task in this session. Steps use checkbox (`- [ ]`) syntax for tracking. 不主动派发子代理；每个任务完成测试后单独提交。

**Goal:** 在不访问现有个人库的独立环境中，交付可用真实PostgreSQL验证的邀请、账号、会话、恢复与隔离基础。

**Architecture:** 新增独立FastAPI联网入口，不复用本机全局会话或初始化SQLCipher、DPAPI、Ollama。认证服务使用PostgreSQL事务和专用最小权限角色；后续健康数据从服务端验证的CurrentUser获取归属，并通过事务局部RLS上下文隔离。A阶段只交付认证API与可验证的基础，不开放朋友使用，不把未实现的营养页面挂到公网入口。

**Tech Stack:** Python3.12、现有FastAPI/Pydantic/httpx/pytest、PostgreSQL16、psycopg3及连接池、argon2-cffi；使用独立联网虚拟环境与依赖锁。React/Vite本阶段不修改。

**Spec:** [已确认设计](../specs/2026-10-19-web-pilot-design.md)，对应第4至6、11及13节交付块A。

## Global Constraints

- “首批为本人和10位朋友，共11个独立账号”；“只面向中国大陆，以个人主体准备服务，每月运行预算上限100元”。
- “现有电脑本地版继续可用，正式个人资料不自动上传”。
- “联网进程不初始化Windows SQLCipher库、DPAPI或Ollama”；必要配置缺失时启动失败，不回退正式本地库。
- “Cookie设置HttpOnly、Secure、SameSite=Lax、Path=/”；默认空闲7天、最长30天后重新登录。
- “默认7天有效、一次兑换”的邀请码；密码“默认至少12字符”；恢复码只保存摘要、一次消费。
- 每阶段添加并运行有效测试，通过后独立Git提交；失败先修复，不删除、跳过测试或降低标准。
- 真正的账号、事务、角色和RLS测试必须使用PostgreSQL，不能用SQLite或内存字典替代。
- 不购买资源、创建外部账号、上传资料、开放端口到外网或发送邀请；测试仅合成资料。

## 范围、依赖与交付顺序

A1独立入口 → A2真实测试数据库及迁移 → A3密码与令牌 → A4账号与邀请 → A5会话与恢复 → A6HTTP保护与身份上下文 → A7初始化与集成验收。

本计划不实施B至F的营养存储、个人照片、记忆、备份、云AI、PWA和部署。A提供其稳定接口；下列任务均完成且测试通过才算A完成。没有数据库运行条件时可以先完成不依赖数据库的单元测试，但数据库任务保持未完成，不能用跳过标记获得全绿。

开始执行时先按using-git-worktrees流程检查可复用隔离工作区；使用实际返回目录，不假定当前分支。检查用户改动，保留无关内容。分别读取本计划、设计与对应技能，再运行现有本地完整测试取得基线；保留输出，不修改原验收记录为联网通过。

## 文件与职责

| 路径 | 责任 |
| --- | --- |
| app/online/__init__.py、config.py、main.py、errors.py | 独立入口、严格配置、错误格式和请求编号 |
| app/online/db.py、migrate.py、migrations/001_auth.sql | 有界连接池、事务、数据库角色及一次性迁移 |
| app/online/auth/types.py、secrets.py、repository.py、service.py | 类型、密码/摘要、限定SQL和认证事务 |
| app/online/auth/sessions.py、recovery.py、limits.py | 会话期限、恢复及数据库共享限速 |
| app/online/auth/http.py、dependencies.py、security.py | HTTP协议、当前用户、Cookie/CSRF/Host/Origin |
| app/online/bootstrap.py | 交互初始化本人账号，一次性引导 |
| app/online_tests/conftest.py、test_*.py | 独立测试目录，不放入现有app/tests以免本地测试隐式加载联网依赖 |
| app/scripts/test_online.py、requirements.online.in、requirements.online.lock.txt | 阶段测试入口与独立依赖 |
| docs/online-foundation.md、docs/online-a-results.md | 启动、配置、初始化及实际证据 |

约束：认证库不得import app.backend.main、storage或ai；业务库不能获得认证表SQL连接。密码、恢复码、Cookie和DSN不写日志；API错误只返回安全信息与request_id。

app/online_tests/conftest.py按任务逐步新增fixture，函数内延迟导入该任务已有实现，不能让A1测试提前import A4或A6。约定：`app_client`只做HTTPS TestClient无lifespan的配置/路由测试，不声称数据库就绪；`db`来自ONLINE_TEST_ADMIN_DSN且隔离schema就绪；`https_client`绑定db、进入完整lifespan并使用https://testserver及相同Origin；`user_a`为仅测试RLS的CurrentUser；`clock`为可调用且有advance(delta: timedelta)的UTC测试时钟；`auth`为AuthService(db, clock)。

A4起的`manager`由fixture在测试schema的真实表中插入本人账号与已锁定引导状态，不依赖A7初始化代码；该fixture不能作为初始化CLI验收。`registered`由A4服务层register创建固定用户名friend的Registration，不依赖A6 HTTP。`register_body`包含新用户名、合成密码与有效邀请码；`run_parallel(count, operation)`启动count个线程并用起跑Barrier并发调用operation(index)，返回每次的值或捕获的OnlineError，其他异常重新抛出使测试失败。fixture只清理本次随机schema和角色；所有PostgreSQL测试套用项目迁移，不改现存数据库。

## 统一接口与测试约定

统一使用下列类型，后续任务不得自行改名：

```python
from dataclasses import dataclass, field
from datetime import datetime
from uuid import UUID

@dataclass(frozen=True)
class CurrentUser:
    id: UUID
    session_id: UUID
    is_invite_manager: bool
    data_revision: int

@dataclass(frozen=True)
class SessionGrant:
    user: CurrentUser
    token: str = field(repr=False)  # 只在创建时给HTTP层，数据库仅存摘要
    csrf: str = field(repr=False)

@dataclass(frozen=True)
class Registration:
    grant: SessionGrant
    recovery_code: str = field(repr=False)  # 只在创建/恢复响应展示

@dataclass(frozen=True)
class InvitationGrant:
    id: UUID
    code: str = field(repr=False)
    expires_at: datetime
```

时间通过构造参数clock: Callable[[], datetime]注入；测试不sleep七天。随机数使用secrets，UUID使用uuid4。注册、登录、恢复服务参数均显式接收source_key；该值由可信来源规则产生，不取请求正文。

命名约定：register/login/authenticate/logout/recover/revoke_session/create_invitation是AuthService的方法，issue_session/count_users是AuthRepository的方法；A5新增`RateLimiter(db: Database, clock)`，其方法为consume_limit。AuthService在A5持有同一个RateLimiter并在业务事务前调用。fixture中的计数读取使用AuthRepository，不为测试开放全局计数HTTP接口。

PowerShell命令在仓库根目录执行；联网解释器为`.venv-online/Scripts/python.exe`，原本地解释器为`.venv/Scripts/python.exe`。新增依赖前检查可安装的版本及Python兼容性，将直接与传递依赖全部锁定、保存版本证据；不修改requirements.lock.txt。

## Task A1：独立配置、应用入口与安全失败

**Files:** Create app/online/__init__.py、config.py、main.py、errors.py、auth/__init__.py、auth/types.py；Test app/online_tests/conftest.py、test_config.py、test_entrypoint.py；Modify .gitignore以忽略.venv-online/和仅本机的联网配置；Create requirements.online.in及锁文件。

**Interfaces:** `OnlineSettings.from_env(env: Mapping[str,str]) -> OnlineSettings`；`create_online_app(settings: OnlineSettings) -> FastAPI`；`OnlineError(code: str, message: str, status: int, fields: dict | None = None)`。在本任务创建前文四个类型，供A2起使用。A2在应用lifespan中打开pool，当前任务不伪造ready数据库。

- [ ] 先准备独立解释器和测试依赖：运行`.venv/Scripts/python.exe -m venv .venv-online`，从现有锁文件提取FastAPI/Pydantic/pytest/httpx的固定版本形成独立输入，加入实测兼容的psycopg及pool、argon2-cffi，联网解释器安装并锁定实际版本。不要因为解释器或pytest缺失而把环境错误当作红灯测试。
- [ ] 编写配置测试：无ONLINE_AUTH_DSN、ONLINE_DATA_DSN、ONLINE_ORIGIN或Base64解码后正好32字节的ONLINE_MASTER_KEY时拒绝；origin必须HTTPS且无路径、userinfo或通配符。运行进程不要求或持有迁移凭据；A2的迁移命令另读ONLINE_MIGRATION_DSN。生产运行身份不得是超级用户或共用迁移身份，身份检查在A2执行。
- [ ] 增加独立导入子进程测试，在导入钩子中拒绝sqlcipher3、app.backend.storage、app.backend.ai，调用create_online_app后仍可启动配置和公开存活检查。

```python
def test_missing_required_settings_is_explicit():
    with pytest.raises(ValueError, match='ONLINE_AUTH_DSN'):
        OnlineSettings.from_env({})

def test_no_health_routes_in_foundation(app_client):
    assert app_client.get('/api/profile').status_code == 404
```

- [ ] 运行`.venv-online/Scripts/python.exe -m pytest app/online_tests/test_config.py app/online_tests/test_entrypoint.py -q`；确认失败原因是缺少目标实现，而非错误解释器。
- [ ] 实现不可变配置类；独立入口只提供GET /health/live返回`{"status":"live"}`，不返回机器路径或密钥。统一错误处理返回`{"error":{"code":...,"message":...,"fields":{},"request_id":...}}`。
- [ ] 完成依赖输入与全量锁文件；忽略.env.online、本机数据库密码、.venv-online/，不忽略可审阅的无密钥配置说明。main导入只定义工厂，无环境变量时允许导入；A7再增加由显式配置加载的工厂启动函数，保持无数据库导入测试可运行。
- [ ] 重新运行上述测试，执行`git diff --check`；只提交本任务文件，提交消息`feat: isolate online application configuration`。

## Task A2：真实PostgreSQL、最小权限与可重复迁移

**Files:** Create app/online/db.py、migrate.py、migrations/001_auth.sql、app/online_tests/test_database.py；Modify app/online_tests/conftest.py；Create docs/online-foundation.md。

**Interfaces:** `Database(settings)`持有auth_pool和data_pool；`auth_transaction()`和`user_transaction(user: CurrentUser)`为上下文管理器；`migrate(dsn: str) -> None`使用独立迁移凭据。每池最大5连接，超时明确错误；user_transaction使用`set_config('app.current_user_id', str(user.id), true)`的事务局部值，退出即复位；RLS策略使用`NULLIF(current_setting('app.current_user_id', true), '')::uuid`，无身份时匹配不到任何用户行。

- [ ] 检查本机PostgreSQL服务、可执行文件、容器运行时。当前只确认PATH没有docker/psql，不能据此断言未安装；检查`.tools`和受控服务清单但不读取正式资料。
- [ ] 优先使用已有隔离PostgreSQL；如需下载便携运行时，核验官方来源及摘要，放入忽略目录`.tools/online-postgres`，监听127.0.0.1独立端口，不安装系统服务或修改全局PATH。不能取得可靠运行时时报告实际阻碍，不伪造数据库测试。
- [ ] conftest仅接受显式ONLINE_TEST_ADMIN_DSN，主机必须回环且库名以shansuan_test_开头；每次运行创建随机schema和临时角色，只清理本次创建的命名空间，不DROP DATABASE或修改现有用户。
- [ ] 迁移器接受受控schema前缀，默认shansuan，测试使用每次生成的随机前缀；仅允许ASCII小写字母、数字和下划线，长度不超过32，SQL标识符用psycopg.sql.Identifier引用。派生独立认证和业务schema，不把固定auth表写进已有库；运行角色的search_path只包含本次授权schema。
- [ ] 先写测试：二次迁移不重复执行；迁移中断完整回滚；运行角色非owner/超级用户/BYPASSRLS；数据角色不能SELECT认证摘要；连接池身份不残留。

```python
def test_user_context_does_not_leak(db, user_a):
    with db.user_transaction(user_a) as conn:
        value = conn.execute("select current_setting('app.current_user_id')").fetchone()[0]
        assert value == str(user_a.id)
    with db.data_pool.connection() as conn:
        value = conn.execute("select current_setting('app.current_user_id', true)").fetchone()[0]
        assert value in (None, '')
```

- [ ] 运行`.venv-online/Scripts/python.exe -m pytest app/online_tests/test_database.py -q`取得有效失败。
- [ ] 001_auth.sql创建版本表、users、invitations、recovery_codes、sessions、privacy_consents、auth_limits、bootstrap_state；UUID主键、timestamptz时间、唯一规范用户名/令牌摘要、有效期约束与外键。认证表位于独立schema，auth角色只获必要SELECT/INSERT/UPDATE及对过期sessions/auth_limits的限定DELETE，data角色无访问权限；创建受RLS保护的最小test-owned表仅由fixture执行以验证连接隔离，不添加真实健康表。
- [ ] 用户名限定3至32位ASCII字母/数字/下划线并casefold，密码不自动trim。users至少包含id、username_norm、password_hash、credential_version、status、is_invite_manager、data_revision、created_at；auth_limits以(operation, hashed_subject, window_start)唯一。session包含id、可空user_id、token_digest、csrf_digest、created_at、last_seen_at、expires_at、revoked_at，匿名20分钟、实名最长30天由服务校验；恢复码包含user_id、digest、used_at；bootstrap_state单行记录initialized、active_members与max_members=11，锁定后更新名额。
- [ ] 用真实数据库运行上述测试及A1测试；记录PostgreSQL版本和角色检查，不输出DSN；提交`feat: add isolated PostgreSQL authentication storage`。

```sql
-- 在fixture选定的随机data schema中创建test_owned并设置运行角色权限后执行。
ALTER TABLE test_owned ENABLE ROW LEVEL SECURITY;
ALTER TABLE test_owned FORCE ROW LEVEL SECURITY;
CREATE POLICY owner_only ON test_owned FOR ALL
USING (owner_id = NULLIF(current_setting('app.current_user_id', true), '')::uuid)
WITH CHECK (owner_id = NULLIF(current_setting('app.current_user_id', true), '')::uuid);
```

## Task A3：密码、令牌及恢复码安全原语

**Files:** Create app/online/auth/secrets.py；使用A1已创建的auth/types.py；Test app/online_tests/test_auth_secrets.py。

**Interfaces:** `hash_password(password: str) -> str`、`verify_password(encoded: str, candidate: str) -> bool`、`new_token() -> str`、`token_digest(token: str) -> bytes`、`new_recovery_code() -> str`、`csrf_for_token(token: str, master_key: bytes) -> str`；类型使用A1创建的四个数据类。

- [ ] 写失败测试：相同密码两次哈希不同但均可验证，错误密码返回False；长度小于12或超过128字符及超过512 UTF-8字节拒绝；允许空格和粘贴，不偷偷trim；128字符内的合法Unicode可验证。

```python
def test_password_hash_is_salted():
    password = 'a valid password 2026'
    first, second = hash_password(password), hash_password(password)
    assert first != second
    assert verify_password(first, password)
    assert not verify_password(first, 'different password')
```

- [ ] 运行`.venv-online/Scripts/python.exe -m pytest app/online_tests/test_auth_secrets.py -q`确认失败。
- [ ] 使用argon2-cffi实现Argon2id，起始参数time_cost=2、memory_cost=19456 KiB、parallelism=1；通过本机测试评估耗时后只能在保持安全依据的情况下提高参数，不为压测降低。随机令牌与恢复码各至少32随机字节，摘要使用SHA-256；恢复码可分组显示但解析必须固定规范。
- [ ] csrf_for_token先用HMAC-SHA256(master_key, 固定标签shansuan:csrf-key:v1)派生CSRF专用子密钥，再HMAC原始会话令牌并Base64URL编码。session只存SHA-256(csrf)，GET session通过HttpOnly Cookie中的令牌重算，不逐次轮换CSRF，避免同账号多标签互相失效。测试同令牌重读稳定、不同令牌不同、无Cookie不能凭数据库摘要构造CSRF；会话轮换后旧CSRF拒绝。

```python
import base64
import hashlib
import hmac

def csrf_for_token(token: str, master_key: bytes) -> str:
    subkey = hmac.new(master_key, b'shansuan:csrf-key:v1', hashlib.sha256).digest()
    value = hmac.new(subkey, token.encode('ascii'), hashlib.sha256).digest()
    return base64.urlsafe_b64encode(value).rstrip(b'=').decode('ascii')
```
- [ ] 增加断言：数据库/日志检测标记找不到密码、原始会话或恢复码；损坏哈希不回显输入，也不抛出内部库信息。令牌摘要不能用作可登录令牌。
- [ ] 重跑原语测试及A1/A2，提交`feat: add password and recovery secret primitives`。

## Task A4：邀请注册及并发名额

**Files:** Create app/online/auth/repository.py、service.py；Test app/online_tests/test_invitations.py。

**Interfaces:** `AuthService(db: Database, clock)`；`create_invitation(manager: CurrentUser, source_key: str) -> InvitationGrant`；`register(username: str, password: str, invitation: str, source_key: str) -> Registration`；`AuthRepository.count_users() -> int`只供管理状态与测试使用。repository内部`issue_session(conn, user_id: UUID, now: datetime) -> SessionGrant`在当前事务创建令牌摘要和CSRF摘要并构造CurrentUser，A5的login/recover复用它，不提前依赖后续sessions.py。

- [ ] 先写真实数据库测试：普通账号不能发邀请；未知、过期、重复邀请码失败；同邀请码20次并发仅1次成功；本人加10个朋友后不能继续注册；不同邀请码竞争最后一个名额只能成功1个；用户名冲突不消耗邀请码；注册异常回滚账号、邀请码消费、恢复码及会话。

```python
def test_one_invitation_has_one_winner(auth, manager, run_parallel):
    invite = auth.create_invitation(manager, 'manager-source')
    results = run_parallel(20, lambda i: auth.register(
        f'friend_{i}', 'valid personal password', invite.code, f'source-{i}'))
    assert sum(isinstance(value, Registration) for value in results) == 1
    assert auth.repo.count_users() == 2
```

- [ ] 运行`.venv-online/Scripts/python.exe -m pytest app/online_tests/test_invitations.py -q`验证并发测试真实失败。
- [ ] 实现：先限制输入并计算密码哈希，再在短事务中按固定顺序锁bootstrap_state及invitation；验证名额与有效期，写账号/恢复摘要/会话并消费邀请。唯一冲突转为安全业务错误，不根据客户端字段授予manager。限速在A5补齐，在A6 HTTP上线前不得对外暴露当前注册服务；本任务不引用尚未创建的limits.py。
- [ ] 管理者仅能列邀请的id、有效期、兑换状态与必要账号状态，不返回健康正文、密码/恢复摘要或原始邀请码历史。邀请码只在创建响应展示一次。
- [ ] 运行并发、回滚和基础全部测试，提交`feat: add atomic invite-only registration`。

## Task A5：登录、会话、恢复与共享限速

**Files:** Create app/online/auth/sessions.py、recovery.py、limits.py；Modify service.py、repository.py；Test app/online_tests/test_sessions.py、test_recovery.py、test_rate_limits.py。

**Interfaces:** AuthService提供`login(username, password, source_key) -> SessionGrant`、`authenticate(token: str) -> CurrentUser`、`logout(token: str) -> None`、`recover(username, recovery_code, new_password, source_key) -> Registration`、`revoke_session(user: CurrentUser, session_id: UUID) -> None`；RateLimiter提供`consume_limit(operation: str, subject: str, maximum: int, seconds: int) -> None`。

- [ ] 用注入时钟写测试：空闲7天、绝对30天失效；使用只刷新last_seen_at不延长绝对期限；注销/恢复/撤销后旧会话立即无效；普通用户不能读或撤销他人会话。
- [ ] 恢复测试：错误和已消费恢复码失败；并发恢复仅一次成功；失败不改密码或撤销正常会话；成功生成新恢复码并撤销全部旧会话，响应不含旧密码。
- [ ] 限速测试：账号10次/15分钟、来源50次/15分钟分别适用于登录和恢复；邀请兑换来源20次/小时；并发和重启服务不能绕过；未知账号走同样的密码验证工作和统一错误。管理者创建邀请20次/小时，防止表无限增长。

```python
def test_recovery_revokes_previous_sessions(auth, registered):
    old = registered.grant.token
    result = auth.recover('friend', registered.recovery_code,
                          'another valid password', 'source')
    with pytest.raises(OnlineError) as error:
        auth.authenticate(old)
    assert error.value.status == 401
    assert auth.authenticate(result.grant.token).id == registered.grant.user.id
```

- [ ] 运行`.venv-online/Scripts/python.exe -m pytest app/online_tests/test_sessions.py app/online_tests/test_recovery.py app/online_tests/test_rate_limits.py -q`确认失败。
- [ ] 共享限速用数据库原子计数和服务端clock确定的UTC固定时间窗，不使用进程内字典或客户端时间。限速消费在独立短事务先提交，不能因后续密码错误或注册事务回滚而退回次数；同时接入A4邀请与注册服务。密码哈希计算放在短事务外，正式提交时重检账号状态和credential_version，防止恢复与登录竞态创建旧密码会话。限速键摘要化，source只信任显式代理列表或socket来源。
- [ ] 会话仅存token与csrf摘要，空闲/绝对期限每次鉴权检查；写last_seen_at可节流但不省略过期验证。失败统一401凭据无效，超额429；注销重复调用保持成功，撤销未知或他人会话返回404。
- [ ] 运行全部认证测试并验证数据库没有原始秘密，提交`feat: add revocable sessions and account recovery`。

## Task A6：HTTP协议、CSRF及当前账号边界

**Files:** Create app/online/auth/http.py、dependencies.py、security.py；Modify main.py；Test app/online_tests/test_auth_http.py、test_access_boundaries.py。

**Interfaces:** `require_user(request: Request) -> CurrentUser`只读验证过的Cookie；`require_csrf(request: Request) -> None`检查当前会话和X-CSRF-Token；认证路由返回安全user及一次性展示字段；SessionGrant仅内部使用，token不能出现在JSON。

HTTP契约的精确JSON：`GET /api/session`返回`{"authenticated":false,"csrf":"<token>"}`（匿名CSRF Cookie不转为长期账号）；认证后返回`{"authenticated":true,"csrf":"<token>","user":{"id":"<uuid>","is_invite_manager":false}}`。`POST /api/auth/register`仅接受`username,password,invitation`，201返回`{"user":{"id":"<uuid>","is_invite_manager":false},"csrf":"<rotated>","recovery_code":"<one-time>"}`；login仅接受`username,password`且200返回user与csrf；recover仅接受`username,recovery_code,new_password`且200返回user、csrf与新恢复码。logout响应204、JSON为空。`POST /api/invitations`无正文、201返回一次性`code,expires_at`；GET列表只返回`id,created_at,expires_at,redeemed_at,status`；sessions列表仅返回`id,created_at,last_seen_at,expires_at,current`，不返回来源IP或完整User-Agent；撤销本人设备返回204。每个包含UUID的任意路径都交叉账号请求验证统一404。

- [ ] 写TestClient真实数据库测试：GET /api/session匿名返回authenticated=false和匿名CSRF；注册/登录/恢复必须匹配匿名会话CSRF与允许Origin；认证后返回authenticated=true、user.id和CSRF，不返回token摘要。
- [ ] 匿名会话采用短期随机Cookie及数据库session记录，user_id可空、期限20分钟；其生成也限速且过期清理。注册/登录成功时撤销匿名会话并轮换Cookie/CSRF，不能让匿名标识变成固定登录会话。
- [ ] Cookie断言HttpOnly/Secure/SameSite=Lax/Path=/；测试base_url使用https://testserver且配置精确origin；生产HTTP配置拒绝。只读session响应和认证响应均Cache-Control: private, no-store。

```python
def test_cookie_is_secure_and_token_not_json(https_client, register_body):
    session = https_client.get('/api/session').json()
    response = https_client.post('/api/auth/register', json=register_body,
        headers={'Origin': 'https://testserver',
                 'X-CSRF-Token': session['csrf']})
    assert response.status_code == 201
    cookie = response.headers['set-cookie'].lower()
    assert all(flag in cookie for flag in ('secure', 'httponly', 'samesite=lax', 'path=/'))
    assert 'token' not in response.json()
```

- [ ] 运行`.venv-online/Scripts/python.exe -m pytest app/online_tests/test_auth_http.py app/online_tests/test_access_boundaries.py -q`确认失败。
- [ ] 固定API：POST auth/register(201)、login(200)、logout(204)、recover(200)；GET auth/sessions；POST auth/sessions/{id}/revoke(204)；POST invitations(201)、GET invitations。请求模型拒绝user_id、is_manager等额外字段；密码字段使用SecretStr且422不返回input正文。
- [ ] 精确Host/Origin校验、禁止跨域放行、忽略不可信转发头；缺少Origin的浏览器写请求拒绝，GET无业务副作用，GET session仅允许必要的匿名会话签发。公开404无内部路径；CSP限制self、禁止嵌套和第三方脚本，样式策略接入现有界面时保留既有行为并单独测试，错误request_id可查询最少诊断。
- [ ] 用两个账号分别列会话/邀请并篡改id和正文确认拒绝；RLS测试在运行data角色下直接读取另一账号测试行得到空、插入他人owner失败。额外测试missing context、连接归还复用与并发100次交替账号，不能残留身份。无权限查看整个邀请列表返回403，猜测他人的单个资源返回404。
- [ ] 全部A测试通过后提交`feat: secure online auth endpoints and identity context`。

## Task A7：首次初始化、完整入口与阶段验收

**Files:** Create app/online/bootstrap.py、app/scripts/test_online.py、app/online_tests/test_bootstrap.py、test_foundation_integration.py、docs/online-a-results.md；Update docs/online-foundation.md。

**Interfaces:** `bootstrap_owner(settings, username: str, password: str) -> Registration`；CLI为`.venv-online/Scripts/python.exe -m app.online.bootstrap`，用户名/密码交互输入，密码不接受命令行参数；`test_online.py`执行全A测试和依赖检查，非0即停止并保存报告。

- [ ] 初始化测试：空数据库创建唯一本人账号；两次或并发引导只能成功一次；本人是manager但无健康读取接口；失败回滚引导状态；日志不含密码和恢复码；命令输出恢复码只在受控终端一次展示。
- [ ] 集成测试完整流程：初始化本人 → 创建邀请 → 注册两个朋友 → 登录两个独立会话 → 重启API → 会话仍有效 → 恢复朋友A → A旧会话失效而B不变 → 撤销B会话 → 复用邀请码失败。验证所有异常输入和限速拒绝不写入多余账号。
- [ ] 运行`.venv-online/Scripts/python.exe -m pytest app/online_tests/test_bootstrap.py app/online_tests/test_foundation_integration.py -q`确认失败。
- [ ] 实现受控CLI、统一测试入口、数据库未配置时明确失败（不pytest.skip），报告写入忽略目录`.test-output/online-a/`，包括环境版本、开始结束时间、命令和退出码；过滤秘密。报告中没有执行的云端/真机步骤列为不在A阶段验收范围。
- [ ] 文档给出精确配置字段、迁移与初始化顺序、独立进程启动方式：`.venv-online/Scripts/python.exe -m uvicorn app.online.main:app_from_env --factory --host 127.0.0.1 --port 18766`；新增`app_from_env() -> FastAPI`读取OnlineSettings后调用工厂，正常import不读取配置。数据库迁移单独运行`.venv-online/Scripts/python.exe -m app.online.migrate`，只在该命令提供ONLINE_MIGRATION_DSN；CLI使用受控引导权限，不把迁移凭据交给API进程。18765本地服务保持不变；测试客户端使用HTTPS，回环HTTP开发不测试相机或承诺生产Cookie可用。
- [ ] 完整验收依次运行：`.venv-online/Scripts/python.exe app/scripts/test_online.py`；`.venv/Scripts/python.exe app/scripts/test_all.py`；`git diff --check`。前者全部A测试0失败0跳过，后者原完整测试和生产构建通过；失败先定位修复，不通过删除断言处理。
- [ ] 在docs/online-a-results.md记录实际结果与文件证据，只对真正执行的步骤写通过。确认没有读写正式个人库、没有公网监听、没有秘密进入Git。提交`feat: complete isolated online account foundation`。

## A交付检查及后续模块约束

- [ ] A1至A7的测试命令实际执行，所有任务有独立提交与证据，工作区状态明确。
- [ ] 本地版全量回归和构建通过；联网入口不暴露现有健康API，没有看起来成功的假营养页面。
- [ ] B必须使用require_user与user_transaction接入营养存储，不自行信任user_id或修改认证schema权限；补齐实体级RLS、复合归属外键与附件授权测试。
- [ ] C接入保存/记忆/数据权利，不改变A会话归属和防跨账号重放边界；账号删除须接入会话撤销。
- [ ] D接入云AI与按账号费用；任务从认证上下文取得账号，不开放健康正文给全局调度权限。
- [ ] E实现真实登录和恢复界面、主屏幕入口及缓存；使用本计划固定HTTP响应，令牌不写浏览器存储。
- [ ] F才做真实资源核价、HTTPS部署、真机与邀请；A完成不能标注“网页版已上线”。

本计划覆盖设计中的A阶段并锁定后续接口；其余B至F仍按设计的独立交付块细化，不把尚无逐项任务的阶段宣称已经可连续自动完成。默认采用当前会话逐项执行与阶段回顾，无需为选择是否派发代理再次询问用户。
