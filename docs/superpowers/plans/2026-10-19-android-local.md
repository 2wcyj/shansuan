# 安卓局域网安装版实施计划

**Goal:** 交付可自行安装、连接现有电脑服务的安卓APK。

**Architecture:** 独立HTTPS代理保留现有电脑服务边界；原生Android WebView固定证书及来源，复用React业务界面。用户已选择最快局域网路线，在本次会话依次实施。

**Tech Stack:** FastAPI/httpx/cryptography；Java/Android API35；React19。

**Spec:** docs/superpowers/specs/2026-10-19-android-local-design.md

## Global Constraints

- 不迁移或写入正式健康资料以进行测试。
- 原服务继续只监听127.0.0.1:18765；手机代理HTTPS18766仅绑定RFC1918地址。
- 所有手机请求需凭据，写操作另需CSRF；只访问固定本机上游。
- APK不内置个人凭据，AndroidKeyStore保存配对信息，不允许任意远程导航。
- 无实体设备时不声称完成实机验收。

## Task 1: HTTPS代理及启动入口

文件：app/backend/mobile.py、app/scripts/mobile.py、app/tests/test_mobile.py、启动手机连接.cmd、停止手机连接.cmd。

- [ ] 使用真实TestClient与隔离本机上游测试未配对403、已配对读写、CSRF拒绝、私密接口拒绝、Host/Origin拒绝、上传及重启上游会话恢复。先运行失败测试。
- [ ] 实现代理，使用固定本机上游及独立CSRF，保留上游数据错误与版本语义；运行测试转绿。
- [ ] 实现DPAPI凭据、IP证书生成、启动/停止与连接文件输出；加入真实TLS和加密配置测试。

## Task 2: APK

文件：app/android/AndroidManifest.xml、app/android/src/cn/shansuan/mobile/MainActivity.java、app/scripts/build_android.py。

- [ ] 准备官方JDK、Android platform35和build-tools35，记录来源与校验摘要，全部保存在.tools/android。
- [ ] 实现连接文件导入、地址校验、证书固定、加密存储、受限WebView、系统图片/拍照选择、返回与重连操作。
- [ ] 使用javac/aapt2/d8/zipalign/apksigner构建，检查签名、manifest和权限。

## Task 3: 手机界面与交付

文件：app/frontend/src/mobile.ts、api.ts、App.tsx、Home.tsx、Profile.tsx、Photo.tsx及必要样式；docs/android-local.md；README.md。

- [ ] 手机端准确说明数据存储在电脑，隐藏电脑管理操作，照片支持系统拍照。
- [ ] 构建前端，运行后端回归与手机视口交互验证。
- [ ] 输出手机安装文件夹，启动已验证代理，记录APK摘要、实际测试与实机待验收项；逐项回填本计划。
