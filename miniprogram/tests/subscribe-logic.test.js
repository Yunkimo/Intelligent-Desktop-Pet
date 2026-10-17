// C3 提醒开启流程（逻辑层）：驱动真实 utils/subscribe.js（2026-10-17 简化版，
// 无微信授权），验证创建/复用/更新提醒的服务端为准幂等语义。
// 由 tests/run-tests.js 或独立运行：node tests/subscribe-logic.test.js

const assert = require('assert');

global.wx = {};

const subscribe = require('../utils/subscribe.js');
const api = require('../utils/api.js');

const calls = [];
function mockApi(reminders) {
  calls.length = 0;
  api.getReminders = async () => {
    calls.push(['getReminders']);
    return reminders;
  };
  api.createReminder = async (data) => {
    calls.push(['createReminder', data]);
    return { id: 5 };
  };
  api.updateReminder = async (id, data) => {
    calls.push(['updateReminder', id, data]);
    return {};
  };
}

const TASK = { id: 9, title: '测试任务', note: '备注', remind_at: '2026-10-20T10:00' };

let passed = 0;
async function check(name, fn) {
  await fn();
  passed += 1;
  console.log('PASS', name);
}

async function main() {
  await check('开启提醒-创建：无既有提醒时创建 phone 提醒', async () => {
    mockApi([]);
    const result = await subscribe.subscribeTaskReminder(TASK);
    assert.strictEqual(result.status, 'on');
    const created = calls.find((c) => c[0] === 'createReminder')[1];
    assert.strictEqual(created.channel, 'phone');
    assert.strictEqual(created.task_id, TASK.id);
    assert.strictEqual(created.remind_at, TASK.remind_at);
    assert.strictEqual(created.title, TASK.title);
    assert.strictEqual(created.body, TASK.note);
  });

  await check('开启提醒-重复：既有提醒时间未变时不重复创建', async () => {
    mockApi([{ id: 5, task_id: 9, channel: 'phone', remind_at: '2026-10-20T10:00' }]);
    const result = await subscribe.subscribeTaskReminder(TASK);
    assert.strictEqual(result.status, 'on');
    assert.match(result.message, /已开启/);
    assert.ok(!calls.some((c) => c[0] === 'createReminder'));
    assert.ok(!calls.some((c) => c[0] === 'updateReminder'));
  });

  await check('开启提醒-时间变更：既有提醒时间不一致时更新', async () => {
    mockApi([{ id: 5, task_id: 9, channel: 'phone', remind_at: '2026-10-20T09:00' }]);
    const result = await subscribe.subscribeTaskReminder(TASK);
    assert.strictEqual(result.status, 'on');
    assert.match(result.message, /已更新/);
    const update = calls.find((c) => c[0] === 'updateReminder');
    assert.strictEqual(update[1], 5);
    assert.strictEqual(update[2].remind_at, TASK.remind_at);
  });

  await check('开启提醒-无提醒时间：明确报错', async () => {
    mockApi([]);
    let thrown = null;
    try {
      await subscribe.subscribeTaskReminder({ ...TASK, remind_at: null });
    } catch (err) {
      thrown = err;
    }
    assert.ok(thrown);
    assert.match(thrown.message, /没有提醒时间/);
  });

  console.log(`\n全部通过：${passed} 项`);
}

main().catch((err) => {
  console.error('FAIL:', err.message);
  process.exit(1);
});
