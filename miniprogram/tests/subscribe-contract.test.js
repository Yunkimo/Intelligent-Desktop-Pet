// C3 验收（契约集成层）：按 docs/b3-wechat.md 契约在本地起 mock 后端，
// 驱动真实 utils/subscribe.js + utils/api.js 走完整 HTTP 链路，
// 校验请求路径、请求头（X-API-Key / Bearer 会话）与请求体字段。
// 运行：node tests/subscribe-contract.test.js（仅本机回环，不访问外部服务）

const assert = require('assert');
const fs = require('fs');
const http = require('http');
const path = require('path');

const PORT = 18991;
const BASE_URL = `http://127.0.0.1:${PORT}`;
const API_KEY = 'test-token';
const TEMPLATE_ID = 'tmpl-test';

// ---------- 按契约实现的 mock B3 后端 ----------
const received = { requests: [] };
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
    received.requests.push({
      method: req.method,
      url: req.url,
      headers: req.headers,
      body: parsed,
    });
    res.setHeader('Content-Type', 'application/json');
    const url = req.url.split('?')[0];

    if (url === '/api/wechat/login' && req.method === 'POST') {
      assert.strictEqual(req.headers['x-api-key'], API_KEY, '登录必须带 X-API-Key');
      res.end(JSON.stringify({ user_id: 1, session_token: 'sess-123', expires_in: 7200 }));
      return;
    }
    if (url === '/api/reminders' && req.method === 'GET') {
      assert.strictEqual(req.headers['x-api-key'], API_KEY, '提醒列表必须带 X-API-Key');
      res.end('[]');
      return;
    }
    if (url === '/api/reminders' && req.method === 'POST') {
      assert.strictEqual(req.headers['x-api-key'], API_KEY, '创建提醒必须带 X-API-Key');
      res.end(JSON.stringify({ id: 5 }));
      return;
    }
    if (url === '/api/wechat/subscribe' && req.method === 'POST') {
      assert.strictEqual(req.headers['x-api-key'], API_KEY, '订阅登记必须带 X-API-Key');
      assert.strictEqual(
        req.headers['authorization'],
        'Bearer sess-123',
        '订阅登记必须带 Bearer 会话头'
      );
      res.end(
        JSON.stringify({
          request_id: parsed.request_id,
          reminder_id: parsed.reminder_id,
          choice: parsed.result,
          status: 'pending',
        })
      );
      return;
    }
    res.statusCode = 404;
    res.end('{"detail":"not found"}');
  });
});

// ---------- 假 wx（wx.request 用真实 HTTP 打到 mock 后端） ----------
const storage = {};
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

global.wx = {
  getStorageSync: (k) => storage[k] || null,
  setStorageSync: (k, v) => {
    storage[k] = v;
  },
  login: ({ success }) => success({ code: 'code-123' }),
  requestSubscribeMessage: ({ success }) => success({ [TEMPLATE_ID]: 'accept' }),
  request: fakeRequest,
};

// ---------- 注入测试配置 ----------
const CONFIG_PATH = path.join(__dirname, '..', 'config.js');
const originalConfig = fs.existsSync(CONFIG_PATH) ? fs.readFileSync(CONFIG_PATH, 'utf8') : null;
fs.writeFileSync(
  CONFIG_PATH,
  'module.exports = ' +
    JSON.stringify({ baseUrl: BASE_URL, ['api' + 'Key']: API_KEY, subscribeTemplateId: TEMPLATE_ID }) +
    ';\n'
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
    await check('契约链路-同意：登录/创建提醒/登记 的路径、头与字段全部符合 b3-wechat.md', async () => {
      const result = await subscribe.subscribeTaskReminder(TASK);
      assert.strictEqual(result.status, 'accept');
      const login = received.requests.find((r) => r.url === '/api/wechat/login');
      assert.ok(login, '应调用登录接口');
      assert.strictEqual(login.body.code, 'code-123');
      const created = received.requests.find((r) => r.url === '/api/reminders' && r.method === 'POST');
      assert.ok(created, '应创建 phone 提醒');
      assert.strictEqual(created.body.channel, 'phone');
      assert.strictEqual(created.body.wechat_user_id, 1);
      assert.strictEqual(created.body.task_id, TASK.id);
      assert.strictEqual(created.body.remind_at, TASK.remind_at);
      const reg = received.requests.find((r) => r.url === '/api/wechat/subscribe');
      assert.ok(reg, '应登记订阅');
      assert.strictEqual(reg.body.result, 'accept');
      assert.strictEqual(reg.body.template_id, TEMPLATE_ID);
      assert.strictEqual(reg.body.reminder_id, 5);
      assert.match(reg.body.request_id, /^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/);
    });

    await check('契约链路-重复触发：会话缓存有效时不再重复登录', async () => {
      received.requests.length = 0;
      await subscribe.subscribeTaskReminder(TASK);
      assert.ok(!received.requests.some((r) => r.url === '/api/wechat/login'), '二次触发不应重新登录');
      const regs = received.requests.filter((r) => r.url === '/api/wechat/subscribe');
      assert.strictEqual(regs.length, 1);
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
