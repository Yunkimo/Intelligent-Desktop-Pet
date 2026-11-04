// C9 验收（契约/联调层）：由 scripts/check_c9_integration.py 启动真实后端（临时数据库），
// 微信上游用 MockTransport（openid=test-<code>）。真实 api.js + session.js 完整客户端管道：
// - 微信登录 → 课程/日程/学期按账号隔离；非本人资源一律 404
// - 注销后下一次业务请求自动重登并恢复（单次重登，不无限重试）
// - WS 握手使用会话令牌（成功连接且不因令牌被拒）
// 外部微信/视觉服务未启用。

const assert = require('node:assert/strict');
const { runtime } = require('./runtime');

const baseUrl = 'http://127.0.0.1:' + process.env.C9_TEST_PORT;
if (!process.env.C9_TEST_PORT) {
  throw new Error('请运行 python scripts/check_c9_integration.py');
}

let currentCode = 'alice';
const rt = runtime({
  config: { baseUrl, apiKey: '' },
  wx: {
    request: (options) => {
      fetch(options.url, {
        method: options.method,
        headers: options.header,
        body: options.data ? JSON.stringify(options.data) : undefined,
      })
        .then(async (response) => {
          const text = await response.text();
          options.success({ statusCode: response.status, data: text ? JSON.parse(text) : null });
        })
        .catch((error) => options.fail({ errMsg: error.message }));
    },
    login: ({ success }) => success({ code: currentCode }),
    showToast: () => {},
    showLoading: () => {},
    hideLoading: () => {},
  },
});
const api = rt.load('utils/api.js');
const session = rt.load('utils/session.js');

let passed = 0;
async function check(name, fn) {
  await fn();
  passed += 1;
  console.log('PASS ' + name);
}

/** 切换微信身份：清会话后下一次业务请求会自动以新 code 登录。 */
function switchUser(code) {
  currentCode = code;
  session.clearSession();
}

async function cleanup() {
  for (const course of await api.getCourses()) {
    await api.deleteCourse(course.id);
  }
  for (const task of await api.getTasks()) {
    await api.deleteTask(task.id);
  }
}

async function main() {
  await check('未登录业务请求自动登录（微信 code → 会话）并返回本人空数据', async () => {
    switchUser('alice');
    const courses = await api.getCourses();
    assert.deepEqual(courses, []);
    const me = await api.authMe();
    assert.ok(Number.isInteger(me.user_id) && me.user_id > 0);
  });

  await check('课程按账号隔离：A 建课 B 不可见，B 访问 A 的资源 404', async () => {
    switchUser('alice');
    const a = await api.createCourse({
      name: 'A的课',
      day_of_week: 1,
      start_time: '08:00',
      end_time: '09:40',
      location: '',
      teacher: '',
      weeks: [],
    });
    switchUser('bob');
    assert.deepEqual(await api.getCourses(), [], 'B 看不到 A 的课');
    const err = await api.updateCourse(a.id, { name: '改名' }).then(
      () => null,
      (e) => e
    );
    assert.strictEqual(err && err.statusCode, 404, '非本人资源按 404 处理');
    const b = await api.createCourse({
      name: 'B的课',
      day_of_week: 2,
      start_time: '10:00',
      end_time: '11:40',
      location: '',
      teacher: '',
      weeks: [],
    });
    switchUser('alice');
    const names = (await api.getCourses()).map((c) => c.name);
    assert.deepEqual(names, ['A的课'], 'A 也看不到 B 的课');
    switchUser('bob');
    await api.deleteCourse(b.id);
    switchUser('alice');
    await api.deleteCourse(a.id);
  });

  await check('日程与提醒按账号隔离：B 看不到 A 的日程，访问 404', async () => {
    switchUser('alice');
    const task = await api.createTask({
      title: 'A的日程',
      note: '',
      due_at: null,
      remind_at: '2026-11-10T15:00:00+08:00',
    });
    switchUser('bob');
    assert.deepEqual(await api.getTasks(), []);
    assert.deepEqual(await api.getReminders(), []);
    const err = await api.updateTask(task.id, { done: 1 }).then(
      () => null,
      (e) => e
    );
    assert.strictEqual(err && err.statusCode, 404);
    switchUser('alice');
    await api.deleteTask(task.id);
  });

  await check('学期配置按账号隔离：A 已配置，B 未配置', async () => {
    switchUser('alice');
    await api.saveSemester({ start_date: '2026-09-07', total_weeks: 18 });
    const a = await api.getSemester();
    assert.strictEqual(a.configured, true);
    assert.strictEqual(a.settings.start_date, '2026-09-07');
    switchUser('bob');
    const b = await api.getSemester();
    assert.strictEqual(b.configured, false);
    assert.strictEqual(b.settings, null);
  });

  await check('注销后业务请求 401 自动重登一次并恢复，不无限重试', async () => {
    switchUser('alice');
    await api.getCourses(); // 先确保已登录
    const revoked = session.token();
    assert.ok(revoked, '此时应有会话令牌');
    await api.authLogout(revoked);
    // 会话已撤销：下一次业务请求应 401 → 自动重登 → 成功（单次恢复）
    const courses = await api.getCourses();
    assert.ok(Array.isArray(courses), '自动重登后请求恢复');
    const me = await api.authMe();
    assert.ok(me.user_id > 0);
  });

  await check('客户端退出后保持未登录：不自动重登，手动登录恢复', async () => {
    switchUser('alice');
    await api.getCourses();
    await session.logout();
    const err = await api.getCourses().then(
      () => null,
      (e) => e
    );
    assert.ok(err && err.loggedOut, '显式退出后业务请求不得自动重新登录');
    await session.login();
    const courses = await api.getCourses();
    assert.ok(Array.isArray(courses), '手动登录后请求恢复');
  });

  await check('配对码：已登录生成 5 分钟有效，未登录被拒', async () => {
    switchUser('alice');
    await api.getCourses();
    const pairing = await api.authPairing();
    assert.ok(typeof pairing.pairing_code === 'string' && pairing.pairing_code.length > 0);
    assert.strictEqual(pairing.expires_in, 300);
    // 显式退出（保持未登录）时请求业务接口应被拒绝
    await session.logout();
    const err = await api.authPairing().then(
      () => null,
      (e) => e
    );
    assert.ok(err && err.loggedOut, '退出后不自动重登，配对码接口同样拒绝');
    await session.login();
  });

  await check('WS 握手使用会话令牌成功（令牌有效不被拒绝）', async () => {
    switchUser('alice');
    await api.getCourses(); // 确保会话
    const ws = new WebSocket(
      baseUrl.replace('http:', 'ws:') + '/ws?token=' + encodeURIComponent(session.token())
    );
    await new Promise((resolve, reject) => {
      const timer = setTimeout(() => reject(new Error('WS open timeout')), 5000);
      ws.addEventListener('open', () => {
        clearTimeout(timer);
        resolve();
      });
      ws.addEventListener('error', () => {
        clearTimeout(timer);
        reject(new Error('WS error'));
      });
    });
    ws.close();
  });

  await cleanup();
  console.log(`\n全部通过：${passed} 项`);
}

main().catch((err) => {
  console.error('FAIL:', err.message);
  process.exit(1);
});
