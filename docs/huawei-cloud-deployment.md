# 在华为云上部署膳算云端版

本文档说明如何把 `app/backend/cloud_main.py` 部署到华为云，并接入 **RDS for PostgreSQL**、**DCS for Redis**、**OBS**、**KMS** 与**华为云模型 API**。

> 资源规格、费用核价、代金券核查、授权页面与手机验收清单见 [华为云资源清单、授权与验收](huawei-resource-plan.md)。
>
> 推荐**同一 HTTPS 站点**：Nginx 同时提供前端静态文件与 `/api` 反向代理，相关文件在 `deploy/huawei/`。

> 本机 Windows 版与云端版互相独立：云端版不读取本机加密数据库，也不会自动迁移本机资料。

## 1. 部署拓扑

```
        ┌──────────────┐
浏览器 ─▶│  ECS + Docker │──▶ RDS for PostgreSQL（账户、业务数据、迁移）
        │  膳算云端容器  │──▶ DCS for Redis（会话、登录限流）
        └──────┬───────┘──▶ OBS（加密后的照片密文）
               └──────────▶ KMS（账户数据密钥包封）
```

| 组件 | 是否必需 | 用途 |
| --- | --- | --- |
| RDS for PostgreSQL | 必需 | 账户、会话持久记录、业务数据、行级安全 |
| KMS | 必需（生产） | 包封每账户数据密钥 |
| DCS for Redis | 推荐 | 多实例共享会话与限流；未配置时回退 PostgreSQL |
| OBS | 可选 | 私密照片存储；未配置时照片接口返回 503 |
| SMTP | 可选 | 密码找回；未配置时该接口返回 503 |

## 2. 前置准备

1. 华为云账号并完成实名认证。
2. 在 **统一身份认证 IAM** 创建程序访问用户，授予最小权限：
   - `KMS Administrator`（或仅目标密钥的加解密权限）
   - `OBS OperateAccess`（可进一步限定到单个桶）
3. 记录以下值：

| 变量 | 获取位置 |
| --- | --- |
| `HUAWEI_CLOUD_PROJECT_ID` | 控制台「我的凭证」→ 项目列表 |
| `HUAWEI_CLOUD_ACCESS_KEY_ID` / `HUAWEI_CLOUD_SECRET_ACCESS_KEY` | IAM → 访问密钥 |
| `KMS_REGION_ID` | 目标区域 ID，例如 `cn-north-4` |

推荐使用**临时凭证**（委托/STS），此时额外设置 `HUAWEI_CLOUD_SECURITY_TOKEN`；AK/SK 长期密钥只用于首次联调。

4. 规划同一 VPC 与子网：ECS、RDS、DCS 放在同一 VPC，安全组仅放行必要端口，不要对公网开放 5432/6379。

## 3. 开通 RDS for PostgreSQL

控制台路径：**数据库 → 云数据库 RDS → 购买数据库实例**。

推荐最小配置：

| 项 | 建议值 |
| --- | --- |
| 引擎 | PostgreSQL 16 |
| 规格 | 2 vCPU / 4 GB 起（联调可更低） |
| 存储 | SSD 云盘 100 GB，开启自动扩容 |
| 部署 | 主备 |
| 端口 | 5432 |
| 网络 | 与 ECS 同 VPC/子网 |
| SSL | **开启**，下载根证书 |

创建完成后：

1. 在「数据库管理」创建业务数据库 `shansuan`。
2. 创建两个账号（不要用管理员账号跑应用）：

```text
shansuan_migrator  —— 迁移用，需要建表/建函数权限
shansuan_runtime   —— 运行时用，仅通过 shansuan_app 角色访问数据
```

完整的角色与授权 SQL 见 [`cloud-database-operations.md`](cloud-database-operations.md)。

3. 在「参数修改」确认 `log_statement` 不要记录明文参数；连接串使用 `sslmode=require`。

对应环境变量：

```text
DATABASE_URL=postgresql+asyncpg://shansuan_runtime:PASSWORD@RDS_HOST:5432/shansuan?sslmode=require
MIGRATION_DATABASE_URL=postgresql+asyncpg://shansuan_migrator:PASSWORD@RDS_HOST:5432/shansuan?sslmode=require
```

> RDS 的内网地址随实例生成；ECS 与 RDS 不同 VPC 时需配置对等连接，不建议直接暴露公网地址。

## 4. 开通 DCS for Redis

控制台路径：**数据库 → 分布式缓存服务 DCS → 购买缓存实例**。

| 项 | 建议值 |
| --- | --- |
| 引擎版本 | Redis 6.0 或 7.0 |
| 实例类型 | 主备 |
| 规格 | 0.5 GB 起 |
| 端口 | 6379 |
| SSL | 开启（推荐） |
| 密码 | 强密码，写入密钥管理，不入库 |

连接串格式：

```text
REDIS_URL=rediss://:PASSWORD@DCS_HOST:6379/0
```

会话与限流键空间：

```text
shansuan:sess:<account_id>:<token_hash>   会话（含 csrf 摘要与过期时间）
shansuan:acct:<account_id>:sessions       账户会话索引，用于改密后整体失效
shansuan:rl:<key_hash>                    固定窗口限流计数
```

行为说明：

- Redis 写入成功时作为共享快路径；Redis 不可用或键缺失时回退 PostgreSQL 中的 `sessions` 表，不会直接放行。
- 修改密码、重置密码会同时失效 PostgreSQL 会话行与 Redis 会话。
- 不配置 `REDIS_URL` 时功能与旧版一致，全部走 PostgreSQL。

## 5. 开通 OBS

控制台路径：**存储 → 对象存储服务 OBS → 创建桶**。

| 项 | 要求 |
| --- | --- |
| 区域 | 与 ECS 相同 |
| 桶策略 | **私有** |
| 版本控制 | **关闭**（否则删除承诺无法兑现） |
| 服务端加密 | SSE 或 SSE-KMS 均可，代码同时会做应用层加密 |
| 跨区域复制 | 关闭 |

```text
OBS_PROVIDER=huawei
OBS_REGION_ID=cn-north-4
OBS_BUCKET=your-private-bucket
```

对象键由服务端生成，形如 `photos/<sha256>.enc`，内容是 AES-256-GCM 密文，不存放原始照片。

## 6. 开通 KMS

控制台路径：**安全 → 数据加密服务 DEW → 密钥管理 → 创建密钥**。

1. 创建对称密钥，记录 **密钥 ID**（不是别名）。
2. 确认 IAM 用户对该密钥有 `kms:cmk:encrypt` / `kms:cmk:decrypt` 权限。
3. 配置：

```text
KMS_PROVIDER=huawei
KMS_REGION_ID=cn-north-4
KMS_KEY_ID=your-key-id
```

启动时应用会用一次性随机密钥做一次真实的加密/解密往返（`check()`），失败则拒绝启动。该探测会产生极小量的 KMS 调用费用。

## 7. 构建镜像并推送 SWR

在仓库根目录执行（构建上下文必须是仓库根目录）：

```bash
export SWR_REGION=cn-north-4
export SWR_ORGANIZATION=your-org
export IMAGE_TAG=0.1.0
bash deploy/huawei/build-and-push.sh
```

脚本会：

1. `docker build -f deploy/cloud/Dockerfile .`
2. 登录 `swr.${SWR_REGION}.myhuaweicloud.com`
3. 推送 `swr.${SWR_REGION}.myhuaweicloud.com/${SWR_ORGANIZATION}/shansuan:${IMAGE_TAG}`

Windows PowerShell 等价命令：

```powershell
docker build -f deploy/cloud/Dockerfile -t shansuan:0.1.0 .
docker tag shansuan:0.1.0 swr.cn-north-4.myhuaweicloud.com/your-org/shansuan:0.1.0
docker login -u cn-north-4@YOUR_AK -p YOUR_LOGIN_TOKEN swr.cn-north-4.myhuaweicloud.com
docker push swr.cn-north-4.myhuaweicloud.com/your-org/shansuan:0.1.0
```

## 8. 首次数据库迁移

迁移只在发布时执行一次，使用迁移账号：

```bash
docker run --rm --env-file deploy/huawei/cloud.env \
  swr.cn-north-4.myhuaweicloud.com/your-org/shansuan:0.1.0 \
  sh -c "alembic -c app/backend/cloud/alembic.ini upgrade head"
```

若镜像中未包含 `alembic.ini` 的相对路径，可在 ECS 上挂载仓库源码执行：

```bash
MIGRATION_DATABASE_URL=... .venv/bin/alembic -c app/backend/cloud/alembic.ini upgrade head
```

首个管理员账号通过 `app/backend/cloud/admin_cli.py` 创建，步骤见 [`cloud-database-operations.md`](cloud-database-operations.md)。

## 9. 在 ECS 上启动

1. 创建 ECS（Ubuntu 22.04 或 EulerOS），安装 Docker，加入与 RDS/DCS 相同的安全组。
2. 把环境变量写入服务器上的 `cloud.env`（权限 600，不要提交到仓库）：

```bash
install -m 600 /dev/null /etc/shansuan/cloud.env
vi /etc/shansuan/cloud.env
```

3. 启动容器：

```bash
docker run -d --name shansuan --restart unless-stopped \
  --env-file /etc/shansuan/cloud.env \
  -p 8080:8080 \
  swr.cn-north-4.myhuaweicloud.com/your-org/shansuan:0.1.0
```

4. 前面放 ELB 或 Nginx 做 TLS 终止。`FRONTEND_ORIGINS` 必须与浏览器实际访问的源完全一致（协议 + 域名 + 端口），否则写请求会返回 403。

## 10. 验证清单

```bash
curl -fsS http://127.0.0.1:8080/health/live
curl -fsS http://127.0.0.1:8080/health/ready
```

期望结果：

| 情况 | `/health/ready` |
| --- | --- |
| 数据库、KMS、OBS 正常，Redis 正常 | `200`，`status=ready` |
| Redis 不可用，其余正常 | `200`，`status=degraded`，`cache.redis=false` |
| 数据库或 KMS 不可用 | `503`，`status=not_ready` |

平台健康检查建议：

- **存活探针**：`/health/live`
- **就绪探针**：`/health/ready`

然后验证业务链路：

1. 创建邀请码并注册账号。
2. 登录后刷新页面，会话应保持。
3. 停止 Redis 实例，确认登录仍可用（回退 PostgreSQL），恢复后会话仍可读取。
4. 修改密码，确认旧会话立即失效。
5. 上传一张测试照片，确认 OBS 中出现 `photos/*.enc` 且内容为密文。

## 11. 安全与运维注意

- 所有云凭证只注入容器环境变量或华为云委托，禁止写入 `VITE_*`、镜像层或 Git。
- 安全组不要对公网开放 5432 / 6379；OBS 桶保持私有。
- 为 RDS 开启自动备份与时间点恢复；为 OBS 配置生命周期规则。
- 关注 KMS 调用量与 DCS 连接数，连接池上限当前为 10（`cloud_main.py`）。
- 需要横向扩容时，多实例必须共用同一个 Redis 与 RDS，并确保 `SESSION_SIGNING_KEY` 完全一致。

## 12. 当前边界

- 云端照片接口完成「规范化 → 加密 → OBS → 草稿」，**尚未接入云端视觉模型**。
- 云端 AI 问答、备份导入导出、持久任务队列尚未实现，不在本部署范围内。
- 本文档步骤需在真实华为云环境执行并回填实际截图与验证结果；首次部署请按控制台当前界面核对参数名称。