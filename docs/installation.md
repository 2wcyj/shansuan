# 安装与离线维护

当前电脑已准备好运行所需环境，双击启动即可。应用不是可随意移动的exe安装包，`.venv`依赖创建它的Python 3.12.14运行环境：`C:/Users/hp/.cache/codex-runtimes/codex-primary-runtime/dependencies/python`。不要删除该目录；在其他兼容Windows电脑可用独立安装的Python3.12重建环境。

## 本地资源

- `.venv/`：本机Python环境，依赖精确版本在`requirements.lock.txt`。
- `.tools/wheels/`：全部27项锁定Python依赖的离线wheel，包含Windows SQLCipher；已从下载缓存核对包名/版本整理，不需要重复联网下载。
- `app/frontend/dist/`：正式页面资源；运行时不需要Node、pnpm或开发服务器。
- `.tools/ollama/`：隔离Ollama0.40.6 Windows CPU运行时。
- `.tools/models/`：qwen3-vl:2b-instruct所需manifest与blob，应用只使用此固定型号。模型许可见`docs/third-party/qwen3-vl-license.txt`。
- `app/resources/`：食物/食谱与来源资料、API契约、交付摘要，不含个人档案。
- `app/resources/delivery-manifest.json`：关键资源大小与SHA256。模型文件较大，核对可能需要数秒。

在当前电脑重建Python环境（维护操作）：先停止应用，用Python3.12创建新的venv，再执行离线安装：

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install --no-index --find-links .tools/wheels -r requirements.lock.txt
```

不要将个人数据目录作为安装目录；不要因环境损坏而覆盖个人数据库。模型与运行时安装到其他电脑需要复制相应资源，Windows账户密钥不能通过复制DPAPI文件迁移，个人资料使用便携备份恢复。

开发维护环境另需Node（当前打包环境Node24）、已有前端node_modules和锁定pnpm-lock.yaml；前端依赖无需在正常运行时安装。`测试.cmd`自动查找当前电脑已准备的Node与Playwright/Edge，测试不访问正式数据。

## 交付自检

完整测试入口`测试.cmd`依次执行：后端全部测试、TypeScript与正式构建、真实Edge操作。任何阶段失败即返回失败，不使用skip/删除断言放行。测试照片为公开测试样本，测试个人档案为合成资料。

程序日常启动只检查已存在资源，禁云、固定回环接口，不自动拉模型/更新/安装依赖。无模型可先手动使用，页面提示未就绪。SQLCipher驱动加载失败时明确报错，不降级明文库。

真实整机重启、物理断网与另一Windows账户的恢复需按验收说明另行执行，不能用环境复制测试代替。
