# 产品目录执行计划

设计依据：../specs/2026-10-19-my-products-design.md

- [ ] 1. app/tests/test_products.py：先测试种子幂等、示意数据隔离、核实条件、过敏/排除/复杂健康拦截、目标依据、未核实禁入统计。运行 pytest 观察失败。
- [ ] 2. domain/products.py：产品校验、六项种子、匹配与设置；独立 product_plan，实际记录快照；支持 g/mL。按第一步测试修复通过。
- [ ] 3. storage/photos.py 扩展本地产品附件，api/products.py 与 main.py 接入；测试 CSRF、版本、幂等、PDF/图片加密及备份恢复；保留 schema 1。
- [ ] 4. Products.tsx、Navigation.tsx、Home.tsx、App.tsx：列表/详情/编辑/过滤/开关/附件；Meals.tsx 追加产品计划组件；Records.tsx 识别产品记录。复用现有样式/状态组件。运行 TypeScript 与生产构建。
- [ ] 5. products-browser.cjs：隔离临时数据运行真实 Edge，验证目录、编辑、推荐与食用、主题、窄屏、错误输入保留、截图及零第三方请求。Browser plugin not available，沿用项目 Playwright。
- [ ] 6. 全部 pytest、原浏览器测试、类型检查及生产构建；记录原有 Android 缺失模块基线问题，不删除或跳过测试。检查差异，提交本任务文件，报告所缺正式商品资料。
