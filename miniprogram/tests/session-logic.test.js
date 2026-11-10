// C9 验收（逻辑层）：驱动真实 utils/session.js。
// - 登录缓存与过期、并发登录合并、强制过期、退出撤销与账号缓存清理
// - 会话代数（epoch）在退出/切换后推进，供调用方丢弃旧账号迟到响应
// 由 tests/run-tests.js 以独立进程运行（node tests/session-logic.test.js）。

const assert = require('assert');
const { runtime } = require('./runtime');

let passed = 0;
async function check(name, fn) {
  await fn();
  passed += 1;
  console.log('PASS', name);
}

function makeSession(rt) {
  const s = rt.load('utils/session.js');
  let logins = 0;
  let nextUser = 1;
  s.setApi({
    baseUrl: 'http://test',
    wechatLogin: async (code) => {
      logins += 1;
      return {
        user_id: nextUser,
        account_id: nextUser,
        session_token: 'token-' + code + '-' + nextUser,
        expires_in: 3600,
      };
    },
    authLogout: async () => {},
  });
  return {
    s,
    logins: () => logins,
    setUser: (id) => {
      nextUser = id;
    },
  };
}

async function main() {
  await check('首次登录换取会话并缓存，token/accountId 可读', async () => {
    const rt = runtime();
    const f = makeSession(rt);
    const session = await f.s.ensureSession();
    assert.strictEqual(session.session_token, 'token-alice-1');
    assert.strictEqual(f.s.token(), 'token-alice-1');
    assert.strictEqual(f.s.accountId(), 1);
    assert.strictEqual(f.logins(), 1);
    // 缓存有效：再次 ensure 不重复登录
    await f.s.ensureSession();
    assert.strictEqual(f.logins(), 1);
  });

  await check('过期会话触发重新登录（1 分钟偏差保护）', async () => {
    const rt = runtime();
    const f = makeSession(rt);
    await f.s.ensureSession();
    // 模拟已过期：把缓存 expires_at 拨到过去
    const key = f.s.sessionKey();
    const cached = rt.storage.get(key);
    rt.storage.set(key, { ...cached, expires_at: Date.now() - 1 });
    await f.s.ensureSession();
    assert.strictEqual(f.logins(), 2);
  });

  await check('并发 ensureSession 合并为一次登录', async () => {
    const rt = runtime();
    const f = makeSession(rt);
    const [a, b, c] = await Promise.all([
      f.s.ensureSession(),
      f.s.ensureSession(),
      f.s.ensureSession(),
    ]);
    assert.strictEqual(f.logins(), 1);
    assert.strictEqual(a.session_token, b.session_token);
    assert.strictEqual(b.session_token, c.session_token);
  });

  await check('forceExpire：保留会话但标记过期，下次 ensure 重新登录', async () => {
    const rt = runtime();
    const f = makeSession(rt);
    await f.s.ensureSession();
    f.s.forceExpire();
    const cached = rt.storage.get(f.s.sessionKey());
    assert.strictEqual(cached.expires_at, 0);
    assert.strictEqual(cached.session_token, 'token-alice-1');
    await f.s.ensureSession();
    assert.strictEqual(f.logins(), 2);
  });

  await check('clearSession：清缓存并推进会话代数，账号切换后旧响应可丢弃', async () => {
    const rt = runtime();
    const f = makeSession(rt);
    await f.s.ensureSession();
    const before = f.s.epochNow();
    f.s.clearSession();
    assert.strictEqual(f.s.token(), null);
    assert.strictEqual(f.s.epochNow(), before + 1);
    f.setUser(2);
    await f.s.ensureSession();
    assert.strictEqual(f.s.accountId(), 2);
    assert.strictEqual(f.s.epochNow(), before + 1, '重登本身不额外推进代数');
  });

  await check('logout：撤销服务端会话、清理账号缓存并清空本地会话', async () => {
    const rt = runtime();
    const f = makeSession(rt);
    let revokedWith = null;
    f.s.setApi({
      baseUrl: 'http://test',
      wechatLogin: async () => ({ session_token: 't', expires_in: 3600, user_id: 1 }),
      authLogout: async (token) => {
        revokedWith = token;
      },
    });
    await f.s.ensureSession();
    // 账号相关业务缓存（如学期配置）应被清理
    const semesterCacheName = 'semester_settings:1';
    rt.storage.set(semesterCacheName, { start_date: '2026-09-07', total_weeks: 18 });
    const result = await f.s.logout();
    assert.strictEqual(result.ok, true);
    assert.strictEqual(result.revoked, true);
    assert.strictEqual(revokedWith, 't');
    assert.strictEqual(f.s.token(), null);
    assert.strictEqual(f.s.isLoggedOut(), true);
    assert.strictEqual(rt.storage.get(semesterCacheName), undefined);
  });

  await check('logout 后保持未登录：ensureSession 不再自动登录，login() 手动恢复', async () => {
    const rt = runtime();
    const f = makeSession(rt);
    await f.s.ensureSession();
    await f.s.logout();
    const err = await f.s.ensureSession().then(
      () => null,
      (e) => e
    );
    assert.ok(err && err.loggedOut, '退出后自动路径不得重新登录');
    assert.strictEqual(f.logins(), 1, '退出后未发生新的登录');
    const session = await f.s.login();
    assert.strictEqual(session.session_token, 'token-alice-1');
    assert.strictEqual(f.logins(), 2, '手动登录才换取新会话');
    assert.strictEqual(f.s.isLoggedOut(), false);
    assert.strictEqual(f.s.token(), 'token-alice-1');
  });

  await check('logout：服务端撤销失败也完成本地登出并如实标记', async () => {
    const rt = runtime();
    const f = makeSession(rt);
    f.s.setApi({
      baseUrl: 'http://test',
      wechatLogin: async () => ({ session_token: 't', expires_in: 3600, user_id: 1 }),
      authLogout: async () => {
        throw new Error('offline');
      },
    });
    await f.s.ensureSession();
    const result = await f.s.logout();
    assert.strictEqual(result.ok, true);
    assert.strictEqual(result.revoked, false);
    assert.strictEqual(f.s.token(), null);
  });

  console.log(`\n全部通过：${passed} 项`);
}

main().catch((err) => {
  console.error('FAIL:', err.message);
  process.exit(1);
});
