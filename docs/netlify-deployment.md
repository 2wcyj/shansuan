# Netlify 前端部署准备

Netlify 只发布 `app/frontend` 的静态前端，不托管膳算 API、PostgreSQL、用户档案、照片或模型。当前配置是部署防错准备，不代表已经上线。

## 连接仓库时使用

- Base directory：`app/frontend`（已写入根目录 `netlify.toml`）
- Build command：`pnpm run build:netlify`
- Publish directory：`dist`
- Node.js：22
- SPA 路由回退：`/*` → `/index.html`（已写入配置）

仓库导入后，必须先在 Netlify 网站设置中加好自定义前端域名，并在该站点的生产环境变量中配置：

| 变量 | 示例 | 是否进入浏览器 |
| --- | --- | --- |
| `VITE_DEPLOY_PLATFORM` | `netlify`（由配置设定） | 是 |
| `VITE_APP_ORIGIN` | `https://app.example.cn` | 是 |
| `VITE_API_BASE_URL` | `https://api.example.cn` | 是 |
| `VITE_COOKIE_SITE_DOMAIN` | `example.cn` | 是 |

示例域名仅说明格式。前端与 API 必须是共享主域下的不同 HTTPS 子域名。构建检查会拒绝缺失/不安全的 API 地址、Netlify 默认域名及跨 cookie 主域的组合。正式 cookie 依赖此同站点关系；API 还必须配置仅允许 `VITE_APP_ORIGIN` 的 CORS 和 credential 响应。

**禁止在任何 `VITE_*` 变量中放密码、访问令牌、数据库连接串、KMS 密钥或其它秘密。** Vite 会把这些变量编译进所有访客都能下载的 JavaScript。秘密只应留在后端云服务环境变量或密钥管理服务。

当前前端静态构建可以执行；云端 API 已实现账号认证、敏感信息授权、租户隔离和部分业务接口，并新增华为云 KMS/OBS/DCS 适配器与生产启动 fail-closed 检查。KMS 仅在合成密钥上做启动/就绪探测，真实华为云资源和 IAM 委托身份仍未创建或验收。照片/云端 AI、隐私附件导出删除、云端完整业务界面及上线安全验收仍未完成。不能填写虚构生产 API，也不应将当前页面部署后当成可用的公共营养服务。待这些流程和验收完成后，才创建生产站点和启用 API 地址。

2026-10-22 前端接入增量：当前版本在云端登录并单独同意健康信息处理后，挂载复用的业务页面；首次账户进入六步档案表单。本机引导仍使用 `/api/session`，云端业务初始化使用 `/api/auth/session`。退出、撤回和账户删除清除 React Query 缓存及 API 会话状态；健康 API 返回 401/428 时关闭业务界面。云端模式不提供本机恢复点、DPAPI 备份表单和未实现的照片/问答入口。真实 Edge 浏览器（合成 API）已验证登录、同意、云端档案草稿 CSRF 写入、撤回、跨账户缓存清理和服务端授权失效；真实云后端与业务前端全流程联调、附件与备份兼容仍未完成，不能据此称为可发布。

后端容器通过 `deploy/cloud/Dockerfile` 构建并监听容器端口 8080。生产至少需要由平台 Secret 注入 `DATABASE_URL`、随机 `SESSION_SIGNING_KEY`、`FRONTEND_ORIGINS`、`KMS_PROVIDER=huawei`、`KMS_REGION_ID`、实际 `KMS_KEY_ID` 以及华为云 IAM 凭据；推荐使用 IAM 临时凭证或委托，避免在容器中长期保存静态 AccessKey。会话与限流可配置 `REDIS_URL` 指向 DCS for Redis。数据库迁移只能由独立迁移角色运行，不能把该凭据给 API 容器。模板见 `deploy/cloud/.env.example`，其中所有值都是占位符。

发布之前还需将 CSP `connect-src` 收窄至最终 API 域名，在预览与生产使用不同 API/数据环境；从大陆不同运营商网络实际检查访问。Netlify 仅接收静态文件请求，前端业务请求直接从浏览器发往独立 API 域名，不配置 Netlify API proxy。
