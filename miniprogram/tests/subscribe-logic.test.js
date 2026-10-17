// C3 验收（逻辑层）：驱动真实 utils/subscribe.js 的纯函数，
// 验证 request_id 格式、会话有效期判定、授权结果分类（拒绝不声称成功）。
// 由 tests/run-tests.js 以独立进程运行（node tests/subscribe-logic.test.js）。

const assert = require('assert');

global.wx = { getStorageSync: () => null, setStorageSync: () => {} };

const subscribe = require('../utils/subscribe.js');

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

  console.log(`\n全部通过：${passed} 项`);
}

main().catch((err) => {
  console.error('FAIL:', err.message);
  process.exit(1);
});
