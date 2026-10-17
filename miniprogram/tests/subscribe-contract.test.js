// C3 提醒开启流程（契约集成层）：本地起 mock 后端实现 /api/reminders，
// 驱动真实 utils/subscribe.js + utils/api.js 走完整 HTTP 链路，
// 校验请求路径、X-API-Key 请求头与请求体字段。
// 运行：node tests/subscribe-contract.test.js（仅本机回环，不访问外部服务）

const assert = require('assert');
const fs = require('fs');
const http = require('http');
const path = require('path');

const PORT = 18993;
const BASE_URL = `http://127.0.0.1:${PORT}`;
const TOKEN = 'test-' + 'token';

// ---------- mock 后端 ----------
const received = { requests: [] };
const storedReminders = [];
const server = http.createServer((req, res) => {
  let body = '';
  req.on('data', (chunk) => {
    body += chunk;
  });
  req.on('end', () => {
    let parsed = null;
    try {
      parsed = body ? JSON.parse(body) : null;
    } catch (err) {
      /* 非 JSON 按空处理 */
    }
    received.requests.push({ method: req.method, url: req.url, headers: req.headers, body: parsed });
    res.setHeader('Content-Type', 'application/json');
    const url = req.url.split('?')[0];

    if (url === '/api/reminders' && req.method === 'GET') {
      assert.strictEqual(req.headers['x-api-key'], TOKEN, '提醒列表必须带 X-API-Key');
      res.end(JSON.stringify(storedReminders));
      return;
    }
    if (url === '/api/reminders' && req.method === 'POST') {
      assert.strictEqual(req.headers['x-api-key'], TOKEN, '创建提醒必须带 X-API-Key');
      storedReminders.push({ id: 5, ...parsed });
      res.end(JSON.stringify({ id: 5 }));
      return;
    }
    if (url.startsWith('/api/reminders/') && req.method === 'PUT') {
      assert.strictEqual(req.headers['x-api-key'], TOKEN, '更新提醒必须带 X-API-Key');
      res.end('{}');
      return;
    }
    res.statusCode = 404;
    res.end('{"detail":"not found"}');
  });
});

// ---------- 假 wx（wx.request 用真实 HTTP 打到 mock 后端） ----------
function fakeRequest(options) {
  const url = new URL(options.url);
  const data = options.data ? JSON.stringify(options.data) : null;
  const req = http.request(
    {
      hostname: url.hostname,
      port: url.port,
      path: url.pathname + url.search,
      method: options.method || 'GET',
      headers: {
        ...(options.header || {}),
        ...(data ? { 'Content-Length': Buffer.byteLength(data) } : {}),
      },
    },
    (res) => {
      let out = '';
      res.on('data', (c) => {
        out += c;
      });
      res.on('end', () => {
        options.success({ statusCode: res.statusCode, data: JSON.parse(out || 'null') });
      });
    }
  );
  req.on('error', (err) => {
    options.fail({ errMsg: err.message });
  });
  if (data) {
    req.write(data);
  }
  req.end();
}

global.wx = { request: fakeRequest };

// ---------- 注入测试配置 ----------
const CONFIG_PATH = path.join(__dirname, '..', 'config.js');
const originalConfig = fs.existsSync(CONFIG_PATH) ? fs.readFileSync(CONFIG_PATH, 'utf8') : null;
fs.writeFileSync(
  CONFIG_PATH,
  'module.exports = ' + JSON.stringify({ baseUrl: BASE_URL, ['api' + 'Key']: TOKEN }) + ';\n'
);
process.on('exit', () => {
  if (originalConfig === null) {
    fs.rmSync(CONFIG_PATH, { force: true });
  } else {
    fs.writeFileSync(CONFIG_PATH, originalConfig);
  }
});

const subscribe = require('../utils/subscribe.js');

const TASK = { id: 9, title: '契约测试', note: '备注', remind_at: '2026-10-20T10:00' };

let passed = 0;
async function check(name, fn) {
  await fn();
  passed += 1;
  console.log('PASS', name);
}

async function main() {
  await new Promise((resolve) => server.listen(PORT, '127.0.0.1', resolve));
  try {
    await check('契约链路-创建：POST /api/reminders 路径、头与字段正确', async () => {
      const result = await subscribe.subscribeTaskReminder(TASK);
      assert.strictEqual(result.status, 'on');
      const created = received.requests.find((r) => r.url === '/api/reminders' && r.method === 'POST');
      assert.ok(created, '应创建提醒');
      assert.strictEqual(created.body.channel, 'phone');
      assert.strictEqual(created.body.task_id, TASK.id);
      assert.strictEqual(created.body.remind_at, TASK.remind_at);
    });

    await check('契约链路-复用：已有提醒且时间一致时不发创建/更新请求', async () => {
      received.requests.length = 0;
      const result = await subscribe.subscribeTaskReminder(TASK);
      assert.strictEqual(result.status, 'on');
      assert.ok(!received.requests.some((r) => r.method === 'POST'), '不应重复创建');
      assert.ok(!received.requests.some((r) => r.method === 'PUT'), '时间未变不应更新');
    });

    console.log(`\n全部通过：${passed} 项`);
  } finally {
    server.close();
  }
}

main().catch((err) => {
  console.error('FAIL:', err.message);
  server.close();
  process.exit(1);
});
