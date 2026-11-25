'use strict';
// Capture real demonstration screenshots with Edge, using an isolated encrypted store.
// Run: node app/scripts/capture-demo.cjs   (or 截取演示截图.cmd)
const path = require('node:path');
const fs = require('node:fs');
const os = require('node:os');
const { spawn } = require('node:child_process');

const ROOT = path.resolve(__dirname, '../..');
const OUTPUT = path.join(ROOT, 'docs', 'screenshots');
const data = fs.mkdtempSync(path.join(os.tmpdir(), 'shansuan-demo-'));
const port = 18881;
const url = `http://127.0.0.1:${port}`;
const delay = ms => new Promise(resolve => setTimeout(resolve, ms));

function loadPlaywright() {
  const candidates = [
    process.env.PLAYWRIGHT_MODULE,
    path.join(os.homedir(), '.cache', 'codex-runtimes', 'codex-primary-runtime',
              'dependencies', 'node', 'node_modules', 'playwright'),
  ].filter(Boolean);
  for (const candidate of candidates) {
    try { return require(candidate); } catch { /* try next */ }
  }
  try { return require('playwright'); } catch { /* no global install */ }
  throw new Error('未找到 Playwright。请设置 PLAYWRIGHT_MODULE 指向 playwright 包目录。');
}

async function waitForServer(server, log) {
  for (let attempt = 0; attempt < 100; attempt += 1) {
    if (server.exitCode !== null) {
      throw new Error(`应用启动失败（退出码 ${server.exitCode}）：${log()}`);
    }
    try {
      const response = await fetch(`${url}/api/session`);
      if (response.ok) return;
    } catch { /* not listening yet */ }
    await delay(200);
  }
  throw new Error(`应用未在 20 秒内就绪：${log()}`);
}

async function main() {
  const { chromium } = loadPlaywright();
  fs.mkdirSync(OUTPUT, { recursive: true });

  let serverLog = '';
  const server = spawn(
    path.join(ROOT, '.venv', 'Scripts', 'python.exe'),
    [path.join(ROOT, 'app', 'scripts', 'run.py'),
     '--data-dir', data, '--port', String(port), '--no-browser', '--no-model'],
    {
      cwd: ROOT,
      windowsHide: true,
      env: { ...process.env, PYTHONUTF8: '1' },
      stdio: ['ignore', 'pipe', 'pipe'],
    },
  );
  server.stdout.on('data', chunk => { serverLog += chunk.toString(); });
  server.stderr.on('data', chunk => { serverLog += chunk.toString(); });

  let browser;
  try {
    await waitForServer(server, () => serverLog);
    browser = await chromium.launch({ channel: 'msedge', headless: true });
    const context = await browser.newContext({
      viewport: { width: 1280, height: 900 },
      deviceScaleFactor: 1,
    });
    const page = await context.newPage();
    page.on('pageerror', error => console.warn('页面异常：', error.message));

    const shot = async (name, options = {}) => {
      await delay(250);
      await page.screenshot({ path: path.join(OUTPUT, name), fullPage: options.fullPage !== false });
      console.log('已保存 docs/screenshots/' + name);
    };
    const open = async route => {
      await page.goto(url + route);
      await page.locator('h1').first().waitFor({ state: 'visible', timeout: 20000 });
      await delay(200);
    };

    // 1. First-run onboarding (the real six-step flow).
    await page.goto(url + '/');
    await page.getByLabel('年龄（岁）', { exact: true }).fill('30');
    await page.getByLabel('公式使用的性别').selectOption('女');
    await page.getByLabel('身高（cm）', { exact: true }).fill('165');
    await page.getByLabel('体重（kg）', { exact: true }).fill('60');
    await page.getByRole('button', { name: '保存并继续', exact: true }).click();
    await page.getByLabel('平均睡眠（小时）').fill('7');
    await page.getByLabel('每周运动（次）').fill('3');
    await page.getByRole('button', { name: '保存并继续', exact: true }).click();
    await page.getByRole('button', { name: '日常营养均衡', exact: true }).click();
    await page.getByLabel('当前最重要的一个目标').selectOption('日常营养均衡');
    await page.getByRole('button', { name: '保存并继续', exact: true }).click();
    await page.getByLabel('健康状况是否已确认').selectOption('明确无');
    await page.getByLabel('过敏信息是否已确认').selectOption('明确无');
    await page.getByRole('button', { name: '保存并继续', exact: true }).click();
    await page.getByRole('button', { name: '清淡', exact: true }).click();
    await page.getByRole('button', { name: '家庭烹饪', exact: true }).click();
    await page.getByRole('button', { name: '保存并继续', exact: true }).click();
    await page.getByRole('button', { name: '确认档案并进入首页' }).click();
    await page.getByRole('heading', { name: '今日营养', exact: true }).waitFor({ timeout: 20000 });

    // 2. One real meal record so the report and home page are not empty.
    await open('/records');
    await page.getByRole('button', { name: '＋ 记一餐', exact: true }).click();
    await page.getByLabel('选择食物添加', { exact: true }).selectOption('usda-168878');
    await page.getByLabel('第1项重量（g）').fill('150');
    await page.getByRole('button', { name: '保存实际记录', exact: true }).click();
    await page.locator('dialog').waitFor({ state: 'detached', timeout: 20000 });

    // 3. Screenshots, in the order they should appear in the README.
    await open('/');
    await shot('01-home.png');

    await open('/meals');
    await shot('02-meals.png');

    await open('/photo');
    await shot('03-photo-analysis.png');

    await open('/records');
    await shot('04-records.png');

    await open('/report');
    await shot('05-report.png');

    await open('/profile');
    await shot('06-profile.png');

    // 4. Mobile layout on the same data.
    await page.setViewportSize({ width: 390, height: 844 });
    await open('/');
    await shot('07-mobile-home.png');

    console.log('\n截图已全部写入 docs/screenshots/');
    console.log('临时数据目录（可删除）：' + data);
  } finally {
    if (browser) await browser.close().catch(() => {});
    if (server.exitCode === null) server.kill();
  }
}

main().catch(error => {
  console.error(error);
  process.exitCode = 1;
});