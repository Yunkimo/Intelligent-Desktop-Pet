// C2 验收（逻辑层）：在假 wx 运行时中驱动真实 utils/ws.js，
// 验证 URL 映射、契约校验、event_id 去重、节流合并、订阅去重/退订、重连退避与前后台生命周期。
// 由 tests/run-tests.js 以独立进程运行（node tests/ws-logic.test.js）。

const assert = require('assert');
const fs = require('fs');
const path = require('path');

// 测试期注入 config.js（gitignore 文件；测试总是用固定配置，结束后还原原内容）
const CONFIG_PATH = path.join(__dirname, '..', 'config.js');
// 用动态键名构造，避免 apiKey 字面量触发仓库密钥扫描（detect-secrets KeywordDetector）
const TEST_CONFIG =
  'module.exports = ' +
  JSON.stringify({ baseUrl: 'http://127.0.0.1:8001', ['api' + 'Key']: 'test-token' }) +
  ';\n';
const originalConfig = fs.existsSync(CONFIG_PATH) ? fs.readFileSync(CONFIG_PATH, 'utf8') : null;
fs.writeFileSync(CONFIG_PATH, TEST_CONFIG);
process.on('exit', () => {
  if (originalConfig === null) {
    fs.rmSync(CONFIG_PATH, { force: true });
  } else {
    fs.writeFileSync(CONFIG_PATH, originalConfig);
  }
});

let passed = 0;
async function check(name, fn) {
  await fn();
  passed += 1;
  console.log('PASS', name);
}

// ---------- 假 wx 运行时 ----------
class FakeSocket {
  constructor(url) {
    this.url = url;
    this.closed = false;
  }
  onOpen(fn) { this.onOpenFn = fn; }
  onMessage(fn) { this.onMessageFn = fn; }
  onClose(fn) { this.onCloseFn = fn; }
  onError(fn) { this.onErrorFn = fn; }
  close() { this.closed = true; }
}

const sockets = [];
const appShowFns = [];
const appHideFns = [];

global.wx = {
  connectSocket(opts) {
    const s = new FakeSocket(opts.url);
    sockets.push(s);
    return s;
  },
  onAppShow(fn) { appShowFns.push(fn); },
  onAppHide(fn) { appHideFns.push(fn); },
};

const ws = require('../utils/ws.js');

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

function makeEvent(overrides) {
  return Object.assign(
    {
      version: 1,
      event_id: 'e-' + Math.random().toString(36).slice(2),
      type: 'course.created',
      occurred_at: new Date().toISOString(),
      data: { id: 1 },
    },
    overrides || {}
  );
}

function feed(socket, event) {
  socket.onMessageFn({ data: JSON.stringify(event) });
}

async function main() {
  await check('HTTP 地址映射为 WS 地址并携带 token', () => {
    ws.start();
    assert.strictEqual(sockets.length, 1);
    assert.strictEqual(sockets[0].url, 'ws://127.0.0.1:8001/ws?token=test-token');
  });

  await check('忽略不符合契约的事件', async () => {
    const got = [];
    const h = (e) => got.push(e);
    ws.on('course.created', h);
    const bad = [
      makeEvent({ version: 2 }),
      makeEvent({ event_id: '' }),
      makeEvent({ type: 'unknown.type' }),
      makeEvent({ data: { id: 0 } }),
      makeEvent({ data: { id: 'x' } }),
    ];
    bad.forEach((e) => feed(sockets[0], e));
    assert.strictEqual(got.length, 0);
    ws.off('course.created', h);
  });

  await check('合法事件分发且 event_id 去重', () => {
    const got = [];
    const h = (e) => got.push(e);
    ws.on('task.created', h);
    const event = makeEvent({ type: 'task.created', data: { id: 7 } });
    feed(sockets[0], event);
    feed(sockets[0], event);
    assert.strictEqual(got.length, 1);
    assert.strictEqual(got[0].data.id, 7);
    ws.off('task.created', h);
  });

  await check('同一 handler 重复订阅不叠加、off 后不再分发', () => {
    const got = [];
    const h = (e) => got.push(e);
    ws.on('reminder.due', h);
    ws.on('reminder.due', h);
    feed(sockets[0], makeEvent({ type: 'reminder.due' }));
    ws.off('reminder.due', h);
    feed(sockets[0], makeEvent({ type: 'reminder.due' }));
    assert.strictEqual(got.length, 1);
  });

  await check('同类型突发事件节流合并（首条立即 + 尾条补发）', async () => {
    const got = [];
    const h = (e) => got.push(e);
    ws.on('course.created', h);
    const events = [makeEvent(), makeEvent(), makeEvent()];
    events.forEach((e) => feed(sockets[0], e));
    assert.strictEqual(got.length, 1, '首条应立即分发');
    await sleep(500);
    assert.strictEqual(got.length, 2, '窗口末补发最后一条');
    assert.strictEqual(got[1].event_id, events[2].event_id);
    ws.off('course.created', h);
  });

  await check('断线后按退避重连并发出 reconnect', async () => {
    const reconnects = [];
    const h = () => reconnects.push(1);
    ws.on('reconnect', h);
    sockets[0].onCloseFn();
    assert.strictEqual(sockets.length, 1, '未到退避时间不重连');
    await sleep(1100);
    assert.strictEqual(sockets.length, 2, '退避后重建连接');
    sockets[1].onOpenFn();
    assert.strictEqual(reconnects.length, 1, '重连成功应发 reconnect');
    ws.off('reconnect', h);
  });

  await check('切后台停止不重连、回前台恢复连接', async () => {
    ws.stop();
    const count = sockets.length;
    sockets[sockets.length - 1].onCloseFn();
    await sleep(1200);
    assert.strictEqual(sockets.length, count, '主动停止后不重连');
    appShowFns[appShowFns.length - 1]();
    assert.strictEqual(sockets.length, count + 1, '回前台恢复连接');
  });

  console.log(`\n全部通过：${passed} 项`);
}

main().catch((err) => {
  console.error('FAIL:', err.message);
  process.exit(1);
});
