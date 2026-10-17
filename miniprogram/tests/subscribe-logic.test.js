// C3 验收（逻辑层 + 流程集成）：驱动真实 utils/subscribe.js。
// 纯函数验证 request_id 格式、会话有效期、授权结果分类；
// 流程测试用 mock 的 api 与 wx 验证同意/拒绝/取消/登记重试（同一 request_id 幂等）。
// 由 tests/run-tests.js 或独立运行：node tests/subscribe-logic.test.js

const assert = require('assert');
const fs = require('fs');
const path = require('path');

// 测试期注入 config.js（gitignore 文件；测试总是用固定配置，结束后还原）
const CONFIG_PATH = path.join(__dirname, '..', 'config.js');
const TEST_CONFIG =
  'module.exports = ' +
  JSON.stringify({
    baseUrl: 'http://127.0.0.1:8001',
    ['api' + 'Key']: 'test-token',
    subscribeTemplateId: 'tmpl-test',
  }) +
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

// 假 wx 运行时（可编程登录与授权行为）
const storage = {};
const wxState = {
  loginCode: 'code-123',
  loginFail: null,
  subscribeResult: 'accept',
  subscribeFail: null,
};
global.wx = {
  getStorageSync: (k) => storage[k] || null,
  setStorageSync: (k, v) => {
    storage[k] = v;
  },
  login: ({ success, fail }) => {
    if (wxState.loginFail) {
      fail({ errMsg: wxState.loginFail });
    } else {
      success({ code: wxState.loginCode });
    }
  },
  requestSubscribeMessage: ({ success, fail }) => {
    if (wxState.subscribeFail) {
      fail({ errMsg: wxState.subscribeFail });
    } else {
      success({ 'tmpl-test': wxState.subscribeResult });
    }
  },
};

const subscribe = require('../utils/subscribe.js');
const api = require('../utils/api.js');

const calls = [];
function mockApi() {
  calls.length = 0; // 每个用例独立记录，避免跨用例断言污染
  storage['sub_flag_' + TASK.id] = null; // 每个用例从「未订阅」状态开始
  api.wechatLogin = async (code) => {
    calls.push(['login', code]);
    return { user_id: 1, session_token: 'sess-token', expires_in: 7200 };
  };
  api.getReminders = async () => {
    calls.push(['getReminders']);
    return [];
  };
  api.createReminder = async (data) => {
    calls.push(['createReminder', data]);
    return { id: 5 };
  };
  api.wechatSubscribe = async (data, token) => {
    calls.push(['subscribe', data, token]);
    return {};
  };
}

const TASK = { id: 9, title: '测试任务', note: '', remind_at: '2026-10-20T10:00' };

let passed = 0;
async function check(name, fn) {
  await fn();
  passed += 1;
  console.log('PASS', name);
}

async function main() {
  await check('request_id 为 UUID v4 格式且互不相同', () => {
    const ids = new Set([subscribe.newRequestId(), subscribe.newRequestId(), subscribe.newRequestId()]);
    assert.strictEqual(ids.size, 3);
    for (const id of ids) {
      assert.match(id, /^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/);
    }
  });

  await check('会话有效判定：有效/过期/缺字段/临界提前过期', () => {
    const now = Date.now();
    const session = { session_token: 't', expires_at: now + 7200 * 1000 };
    assert.strictEqual(subscribe.isSessionValid(session, now), true);
    assert.strictEqual(subscribe.isSessionValid({ ...session, expires_at: now - 1 }, now), false);
    assert.strictEqual(subscribe.isSessionValid({ session_token: 't' }, now), false);
    assert.strictEqual(subscribe.isSessionValid({ ...session, expires_at: now + 30 * 1000 }, now), false);
  });

  await check('授权结果分类：accept 才声称成功，其余不误导用户', () => {
    assert.deepStrictEqual(subscribe.classifyResult('accept'), {
      ok: true,
      message: '已登记订阅，到期将通过微信提醒',
    });
    for (const result of ['reject', 'ban', 'filter']) {
      const c = subscribe.classifyResult(result);
      assert.strictEqual(c.ok, false);
      assert.match(c.message, /未授权订阅/);
    }
    assert.deepStrictEqual(subscribe.classifyResult('unknown'), { ok: false, message: '' });
  });

  await check('流程-同意：登录→建 phone 提醒→登记 accept，会话存本地', async () => {
    mockApi();
    wxState.subscribeResult = 'accept';
    wxState.subscribeFail = null;
    const result = await subscribe.subscribeTaskReminder(TASK);
    assert.strictEqual(result.status, 'accept');
    const create = calls.find((c) => c[0] === 'createReminder')[1];
    assert.strictEqual(create.task_id, TASK.id);
    assert.strictEqual(create.channel, 'phone');
    assert.strictEqual(create.wechat_user_id, 1);
    assert.strictEqual(create.remind_at, TASK.remind_at);
    const reg = calls.find((c) => c[0] === 'subscribe')[1];
    assert.strictEqual(reg.result, 'accept');
    assert.strictEqual(reg.template_id, 'tmpl-test');
    assert.ok(storage.wechat_session.session_token);
  });

  await check('流程-拒绝：如实登记 rejected，不声称订阅成功', async () => {
    mockApi();
    wxState.subscribeResult = 'reject';
    const result = await subscribe.subscribeTaskReminder(TASK);
    assert.strictEqual(result.status, 'reject');
    assert.match(result.message, /未授权订阅/);
    const reg = calls.find((c) => c[0] === 'subscribe')[1];
    assert.strictEqual(reg.result, 'reject');
  });

  await check('流程-取消：用户关闭弹窗，不登记、不报错', async () => {
    mockApi();
    wxState.subscribeFail = 'requestSubscribeMessage:fail cancel';
    const result = await subscribe.subscribeTaskReminder(TASK);
    assert.strictEqual(result.status, 'cancel');
    assert.ok(!calls.some((c) => c[0] === 'subscribe'));
  });

  await check('流程-已订阅后不重复弹授权框、不重复登记', async () => {
    mockApi();
    wxState.subscribeResult = 'accept';
    wxState.subscribeFail = null;
    // 第一次：正常订阅，登记 accept 并记录本地状态
    const first = await subscribe.subscribeTaskReminder(TASK);
    assert.strictEqual(first.status, 'accept');
    const regs1 = calls.filter((c) => c[0] === 'subscribe');
    assert.strictEqual(regs1.length, 1);
    // 第二次：本地已标记订阅过 → 不弹授权、不再登记
    let dialogCalls = 0;
    const original = global.wx.requestSubscribeMessage;
    global.wx.requestSubscribeMessage = () => {
      dialogCalls += 1;
      original({ success: () => {}, fail: () => {} });
    };
    const second = await subscribe.subscribeTaskReminder(TASK);
    assert.strictEqual(second.status, 'already');
    assert.match(second.message, /已订阅过/);
    assert.strictEqual(dialogCalls, 0, '已订阅后不应再弹授权框');
    const regs2 = calls.filter((c) => c[0] === 'subscribe');
    assert.strictEqual(regs2.length, 1, '已订阅后不应重复登记');
    global.wx.requestSubscribeMessage = original;
    storage['sub_flag_' + TASK.id] = null;
  });

  await check('流程-服务端 409 视为已订阅：友好提示且记录本地状态', async () => {
    mockApi();
    wxState.subscribeResult = 'accept';
    wxState.subscribeFail = null;
    api.wechatSubscribe = async () => {
      throw new Error('HTTP 409：reminder_already_registered');
    };
    const result = await subscribe.subscribeTaskReminder(TASK);
    assert.strictEqual(result.status, 'already');
    assert.match(result.message, /已订阅过/);
    assert.strictEqual(storage['sub_flag_' + TASK.id], 'done');
    storage['sub_flag_' + TASK.id] = null;
  });

  await check('流程-拒绝后给出恢复授权指引，允许再次尝试', async () => {
    mockApi();
    wxState.subscribeResult = 'reject';
    wxState.subscribeFail = null;
    const result = await subscribe.subscribeTaskReminder(TASK);
    assert.strictEqual(result.status, 'reject');
    assert.match(result.message, /授权管理/);
    assert.strictEqual(storage['sub_flag_' + TASK.id], 'reject');
    // 拒绝状态不阻断再次尝试：清掉标记后仍会走授权流程（下一用例覆盖）
    storage['sub_flag_' + TASK.id] = null;
  });

  await check('流程-登记重试：网络失败后复用同一 request_id 重试，不重复累计', async () => {
    wxState.subscribeResult = 'accept';
    wxState.subscribeFail = null;
    let attempts = 0;
    const requestIds = [];
    api.wechatSubscribe = async (data) => {
      attempts += 1;
      requestIds.push(data.request_id);
      if (attempts === 1) {
        throw new Error('网络请求失败：connection reset');
      }
      return {};
    };
    api.wechatLogin = async () => ({ user_id: 1, session_token: 'sess', expires_in: 7200 });
    api.getReminders = async () => [];
    api.createReminder = async () => ({ id: 5 });
    wxState.subscribeResult = 'accept';
    const result = await subscribe.subscribeTaskReminder(TASK);
    assert.strictEqual(result.status, 'accept');
    assert.strictEqual(attempts, 2);
    assert.strictEqual(requestIds[0], requestIds[1], '重试必须复用同一 request_id（契约幂等）');
  });

  console.log(`\n全部通过：${passed} 项`);
}

main().catch((err) => {
  console.error('FAIL:', err.message);
  process.exit(1);
});
