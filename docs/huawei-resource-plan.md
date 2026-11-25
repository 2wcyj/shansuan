# 华为云资源清单、授权与验收

> 本文件只描述**需要开通什么、到哪里授权、如何验收**，不创建任何收费资源，也不记录任何密码、AK/SK 或验证码。
> 金额未核实：本环境没有你的账号，无法读取实时价格。请在控制台「价格计算器」按下方规格与区域核价，再决定是否下单。

## 1 目标形态：同一 HTTPS 站点

```text
浏览器（手机移动网络 / 电脑）
   │  https://<你的域名>/
   ├── 静态前端（React 构建产物）
   └── https://<你的域名>/api/...  →  Nginx 反代  →  FastAPI:8080
                                        ├── RDS for PostgreSQL
                                        ├── DCS for Redis
                                        ├── OBS（照片密文）
                                        ├── KMS（账户密钥包封）
                                        └── 华为云模型 API
```

- 前端与 API **同源同域名**，Cookie 为同站，`FRONTEND_ORIGINS=https://<你的域名>`。
- 构建前端时 **不要设置** `VITE_API_BASE_URL`，请求会走相对路径 `/api`。
- 已提供：`deploy/huawei/nginx.conf`、`deploy/huawei/docker-compose.yml`、`deploy/huawei/build-frontend.sh`。

## 2 需要开通的资源与规格

| 资源 | 规格起点（可按预算下调） | 关键设置 | 用途 |
| --- | --- | --- | --- |
| ECS | 4 vCPU / 8 GB；系统盘 100 GB SSD；Ubuntu 22.04 或 EulerOS；同 VPC 私网 | 绑定 EIP；安全组仅开 80/443 与 SSH；安装 Docker + Compose | 运行 Nginx + FastAPI 容器 |
| RDS for PostgreSQL | PostgreSQL 16；2 vCPU / 4 GB；SSD 100 GB；主备 | 端口 5432；**SSL 开启**；仅放行 ECS 私网；自动备份 7 天 | 账户、业务数据、RLS、迁移 |
| DCS for Redis | Redis 6.0/7.0；主备；0.5 GB 起 | 端口 6379；**SSL 开启**；设置访问密码（只在控制台生成） | 会话、登录限流（故障回退 PG） |
| OBS | 标准存储；单桶 | **私有**；**关闭版本控制**；SSE 开启；仅内网访问 | 存放 AES-GCM 照片密文 |
| DEW / KMS | 1 把对称 CMK | 记录**密钥 ID**（非别名）；授权给运行身份 | 包封每账户数据密钥 |
| 模型服务 | ModelArts Studio（MaaS）在线推理，OpenAI 兼容接口 | 记录 Base URL、模型名、API Key；开通所需模型（文本 + 视觉各一） | 云端问答与照片识别 |
| SWR | 组织 + 镜像仓库 | 私有 | 存放后端镜像 |
| EIP / 带宽 | 按需，1–5 Mbps 起 | 与 ECS 绑定 | 公网访问 |
| DNS + SSL 证书 | 域名 1 个；证书 1 张 | 备案（如需）；证书绑定域名 | 同站 HTTPS |

> 如果预算紧张：RDS 可先单机版，DCS 可用最小规格，OBS/KMS 只在启用照片时必需；模型不可用时问答与照片识别会返回 503，其余功能仍可用。

## 3 费用核价方法（不提供未经核实的金额）

1. 打开华为云控制台 →「费用中心」→「价格计算器」。
2. 选择区域（例如华北-北京四 `cn-north-4`），依次加入 ECS、RDS、DCS、OBS、KMS、SWR、EIP。
3. 按上表规格填写，选择「包年包月」或「按需」，导出报价单。
4. 重点核对：
   - RDS 主备接近双倍价格；
   - KMS 按密钥数 + 调用次数计费，启动探测与每账户密钥包封都会产生调用；
   - OBS 按存储 + 请求 + 公网流量计费，照片走内网可减少流量；
   - 模型 API 按 token 计费，问答约数百 token/次，照片识别更高。
5. 将报价单金额填入 `docs/competition/costs.md` 的空白处，并注明查询日期与区域。

## 4 赛事代金券

- 代金券通常在「费用中心 → 优惠与折扣 → 代金券」查看余额、适用范围与有效期。
- 是否发放、能否用于 RDS/DCS/ModelArts，取决于赛事通知与券面说明，**不能假定通用**。
- 下单前在结算页确认代金券勾选后实付金额；若券不适用，页面会提示。
- 本仓库不记录券码，也不需要你提供券码。

## 5 创建顺序

1. **VPC/子网/安全组**：ECS、RDS、DCS 放同一 VPC。
2. **RDS**：创建实例 → 建库 `shansuan` → 建迁移账号与运行账号 → 开 SSL → 下载 CA。
3. **DCS**：创建实例 → 开 SSL → 记录连接地址（密码只在控制台设置）。
4. **OBS**：创建私有桶 → 关闭版本控制 → 开 SSE。
5. **KMS**：创建对称密钥 → 记录密钥 ID → 给运行身份授权。
6. **模型服务**：在 MaaS 控制台开通模型 → 记录 Base URL、模型名、API Key。
7. **SWR**：创建组织 → 推送镜像。
8. **ECS**：安装 Docker → 拷贝 `cloud.env`、`deploy/huawei/` 与前端 `web/`。
9. **证书**：申请/上传证书 → 放到 ECS 的 `/etc/shansuan/tls/`。
10. **DNS**：A 记录指向 EIP。
11. **迁移**：用迁移账号执行 Alembic `upgrade head`。
12. **启动**：`docker compose up -d`。

## 6 需要你在华为云页面完成的授权

| 页面 | 操作 | 说明 |
| --- | --- | --- |
| 控制台首页 → 实名认证 | 完成实名 | 未实名无法购买 |
| 统一身份认证 IAM → 用户/委托 | 创建程序访问身份，授予 KMS 加解密、OBS 桶读写 | 优先用**委托/临时凭证**，不要长期 AK/SK |
| IAM → 访问密钥 | 如必须用 AK/SK，由你本人创建并只粘贴到服务器 `cloud.env` | **不要发给我** |
| DEW/KMS → 密钥 | 创建密钥，记录密钥 ID | 授权到运行身份 |
| OBS → 桶 | 创建私有桶，关闭版本控制 | 桶名写入 `cloud.env` |
| RDS → 实例 → 账号管理 | 创建迁移账号与运行账号 | 密码只在控制台设置，随后写入服务器 |
| DCS → 实例 | 开 SSL，设置访问密码 | 同上 |
| ModelArts Studio | 开通模型，创建 API Key 并记录 Base URL | API Key 只写入服务器 |
| SWR → 组织 | 创建组织 | 推送镜像时登录 |
| 费用中心 → 代金券 | 确认适用性与余额 | 不涉及券码提交 |
| DNS / 证书管理 | 配置域名与证书 | 用于同站 HTTPS |
| 安全组 | 放行 80/443/SSH；禁止公网 5432/6379 | 最小暴露 |

**安全边界**：你只需在服务器上把真实值写入 `/etc/shansuan/cloud.env`（权限 600）。任何步骤都不需要在对话中发送密码、AK/SK、API Key 或验证码。

## 7 服务器侧准备（不需要云权限）

```bash
# 1) 构建前端（本地或 CI，同源模式）
bash deploy/huawei/build-frontend.sh        # 输出 deploy/huawei/web

# 2) 构建并推送后端镜像
SWR_REGION=cn-north-4 SWR_ORGANIZATION=<你的组织> IMAGE_TAG=0.1.0 \
  bash deploy/huawei/build-and-push.sh

# 3) 上传到 ECS
scp -r deploy/huawei <user>@<ecs>:/opt/shansuan/

# 4) 服务器上创建配置
install -m 600 /dev/null /etc/shansuan/cloud.env
vi /etc/shansuan/cloud.env     # 按 deploy/cloud/.env.example 填真实值
cat > /etc/shansuan/compose.env <<'EOF'
SHANSUAN_IMAGE=swr.cn-north-4.myhuaweicloud.com/<你的组织>/shansuan:0.1.0
SHANSUAN_ENV_FILE=/etc/shansuan/cloud.env
WEB_ROOT=/opt/shansuan/huawei/web
TLS_DIR=/etc/shansuan/tls
EOF

# 5) 启动
cd /opt/shansuan/huawei
docker compose --env-file /etc/shansuan/compose.env config   # 先校验
docker compose --env-file /etc/shansuan/compose.env up -d
docker compose logs -f backend
```

## 8 验收清单

### 8.1 基础可用

- [ ] `https://<域名>/` 返回前端页面
- [ ] `https://<域名>/health/live` 返回 `{"status":"ok"}`
- [ ] `https://<域名>/health/ready` 返回 `status=ready`，且 `dependencies.database=true`
- [ ] Redis 正常时 `cache.redis=true`；停 Redis 后变为 `degraded` 但登录仍可用

### 8.2 业务闭环

- [ ] 邀请码注册 → 登录 → 刷新后会话保持
- [ ] 完成档案与健康信息同意
- [ ] 生成三餐建议；过敏原冲突不出现在候选中
- [ ] 记录一餐 → 首页与报告同步
- [ ] 上传照片 → OBS 出现 `photos/*.enc` → 识别返回候选 → 人工修订 → 确认记餐
- [ ] 问答返回固定安全文本，数字来自记录，不出现模型自由数字
- [ ] 7/30 天报告切换正常，空日不补零
- [ ] 血压/心率可同日多条，删除后报告点消失
- [ ] 修改密码后旧会话失效

### 8.3 安全与隔离

- [ ] 两个账号互相看不到对方记录、照片、报告
- [ ] 不登录访问 `/api/` 业务接口返回 401/403
- [ ] 跨站 Origin 的写请求被拒绝（403）
- [ ] 错误响应不含密钥、内网地址、SQL
- [ ] OBS 对象无法通过公网 URL 直接访问

### 8.4 手机移动网络真实验收

- [ ] 手机关闭 Wi-Fi、仅用移动数据访问 `https://<域名>/`
- [ ] 登录、建档、记一餐、看报告、上传照片全部成功
- [ ] `http://` 自动跳转 `https://`，证书无警告
- [ ] 弱网下重复提交不产生重复记录
- [ ] 记录截图（含时间与网络状态），存 `docs/screenshots/`

## 9 回滚

- 镜像：`docker compose down && SHANSUAN_IMAGE=<旧镜像> docker compose up -d`
- 数据库：Alembic `downgrade -1`，执行前先做 RDS 快照
- 域名/证书：保留上一份 `nginx.conf` 与证书副本

## 10 当前状态

- 代码与部署包：就绪
- 云端 AI：已接入华为云模型 API，**未用真实密钥验证**
- 真实资源：**未创建**
- 公网访问与手机验收：**未执行**