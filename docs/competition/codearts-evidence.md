# CodeArts 使用证据

> 只记录本会话内真实发生的操作。历史其他工具完成的工作不并入 CodeArts 成果。

## 1 会话信息

| 项 | 值 |
| --- | --- |
| 工具 | 华为云码道 CodeArts 代码智能体 |
| 日期 | 2026-11-25 |
| 项目 | `C:\Users\hp\Desktop\食品` |
| 分支 | `main` |
| 起始提交 | `158b69b` |

## 2 本会话完成的动作

### 2.1 隐私与仓库整理

- 识别并隔离根目录 3 张身份证照片至仓库外目录
- 核查 `git diff --cached` 为空、`git log --all` 无照片历史
- `.gitignore` 增加合同、汇报 PPT、手机连接、软著输出、根目录图片等规则

### 2.2 华为云适配（代码）

| 文件 | 动作 |
| --- | --- |
| `app/backend/cloud/kms.py` | 新增 `HuaweiKeyManager`，保留阿里云旧实现 |
| `app/backend/cloud/object_store.py` | 新增 `HuaweiObjectStore` |
| `app/backend/cloud/redis_store.py` | 新增会话/限流存储层 |
| `app/backend/cloud/auth.py` | 接入 Redis 双写与故障回退 |
| `app/backend/cloud_main.py` | 装配 Redis 与就绪探针 |
| `deploy/cloud/requirements.lock.txt` | 移除阿里云包，固定华为云 SDK 与 redis 版本 |
| `deploy/cloud/.env.example` | 改为华为云变量 |
| `deploy/cloud/Dockerfile` | 构建期导入检查改为华为云 SDK |

### 2.3 部署与文档

- `docs/huawei-cloud-deployment.md`
- `deploy/huawei/build-and-push.sh`、`run-ecs.sh`
- `app/scripts/capture-demo.cjs`、`截取演示截图.cmd`
- README 增补华为云与 Demo 章节
- 修正 `cloud-multiplayer-architecture.md`、`netlify-deployment.md` 的阿里云表述
- 新增 `docs/competition/` 全套审计材料

### 2.4 测试

| 命令 | 结果 |
| --- | --- |
| `pytest app/tests/cloud/test_huawei_cloud.py` | 7 passed |
| `pytest app/tests/cloud/test_cloud_env_contract.py` | 3 passed |
| `pytest test_huawei_cloud + test_object_store + test_cloud_env_contract + test_kms -k not repository...` | 19 passed, 1 deselected |
| `py_compile` 全部改动文件 | 通过 |
| `bash -n deploy/huawei/*.sh` | 通过 |
| `node --check app/scripts/capture-demo.cjs` | 通过 |
| `pytest app/tests/cloud/test_redis_store.py` | 本环境 5 failed（WinError 10051），需正常环境复跑 |
| `pytest app/tests/test_cloud_boot.py` | 本环境因 loopback 受限失败，需正常环境复跑 |

## 3 未使用的能力

本会话**未调用**华为云官方 Skills 或 MCP 服务；未使用 ModelArts、MindSpore。材料中不得写"使用 Skills 完成模型训练"。

## 4 后续需补充的证据

- [ ] CodeArts 界面截图（会话、文件改动、测试输出）
- [ ] 华为云控制台资源创建截图（由用户操作）
- [ ] 真实部署后的访问与健康检查截图
- [ ] Skills 实际名称与版本（若后续使用）

## 5 可核验方式

```powershell
git status --short
git diff --stat
.\.venv\Scripts\python.exe -m pytest app/tests/cloud/test_huawei_cloud.py app/tests/cloud/test_cloud_env_contract.py -q
```