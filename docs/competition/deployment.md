# 云部署状态与复现

## 1 状态

| 项目 | 状态 | 说明 |
| --- | --- | --- |
| 部署包 | 就绪 | `deploy/cloud/Dockerfile`、`deploy/cloud/requirements.lock.txt` |
| 配置示例 | 就绪 | `deploy/cloud/.env.example`（华为云变量，全部占位符） |
| 构建/推送脚本 | 就绪·未执行 | `deploy/huawei/build-and-push.sh` |
| 同站部署包 | 就绪·未执行 | `deploy/huawei/nginx.conf`、`docker-compose.yml`、`build-frontend.sh` |
| 华为云模型 API | 已接入·未验证 | `cloud/model_client.py`、`api/cloud_ai.py`（`/api/chat`、`/api/analyses/{id}/recognize`） |
| ECS 启动脚本 | 就绪·未执行 | `deploy/huawei/run-ecs.sh` |
| 部署指导 | 就绪 | `docs/huawei-cloud-deployment.md` |
| RDS for PostgreSQL | 未创建 | 需用户实名与付费确认 |
| DCS for Redis | 未创建 | 同上 |
| OBS 桶 | 未创建 | 同上 |
| DEW/KMS 密钥 | 未创建 | 同上 |
| ECS / SWR | 未创建 | 同上 |
| 域名/备案/HTTPS | 未完成 | 需用户办理 |
| 公网 Demo | 无 | 不得用 localhost 或假地址占位 |

## 2 复现步骤

1. 按 `docs/huawei-cloud-deployment.md` 开通 RDS、DCS、OBS、KMS。
2. 复制 `deploy/cloud/.env.example` 为服务端 `cloud.env`，填入真实值，权限设为 600。
3. `bash deploy/huawei/build-and-push.sh` 构建并推送镜像。
4. 用迁移角色执行 Alembic `upgrade head`。
5. `bash deploy/huawei/run-ecs.sh <镜像地址>` 启动容器。
6. 验证 `/health/live` 与 `/health/ready`：
   - 全依赖正常 → `status=ready`
   - Redis 掉线 → `200 status=degraded cache.redis=false`
   - 数据库或 KMS 掉线 → `503 not_ready`

## 3 回滚

- 镜像回滚：`docker rm -f shansuan && docker run ... <上一版本镜像>`
- 数据库回滚：Alembic `downgrade -1`，执行前先做 RDS 快照
- 配置回滚：保留上一份 `cloud.env` 副本（含密钥，仅存于服务器）

## 4 未完成项

- 未做真实云探测；启动时 KMS `check()` 的计费与耗时需实测
- 未做脱敏监控接入（阶段 7 待办）
- 未做备份恢复演练
- 云端 AI 已接入代码但**未用真实模型密钥验证**；模型调用在请求内同步完成，尚无持久 Worker 与重试队列

## 5 环境阻碍记录

本机沙箱无法访问 loopback，导致容器/应用无法在此启动验证；首次真实执行需在用户本机或 ECS 上完成，并把结果回填到本文件。