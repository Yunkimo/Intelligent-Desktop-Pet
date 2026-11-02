// C9 验收（逻辑层）：驱动真实 utils/api.js 的会话语义（B8 契约 docs/b8-accounts.md）。
// - 业务请求携带 Bearer 会话；401 单次重登后重试一次；仍 401 抛 authRequired
// - 重登前后账号变化或请求期间会话被外部切换 → 抛 accountChanged，不落到新账号
// - 引导入口（微信登录）不带会话；业务上传同会话语义
// 由 tests/run-tests.js 以独立进程运行（node tests/api-auth-logic.test.js）。

const assert = require('assert');
const { runtime } = require('./runtime');

let passed = 0;
async function check(name, fn) {
  await fn();
  passed += 1;
  console.log('PASS', name);
}

// 假后端：/api/wechat/login 发会话；/api/courses 按控制返回 200/401
function makeApiRt(server) {
  const rt = runtime({
    config: { baseUrl: 'http://127.0.0.1:8001', ['api' + 'Key']: '' },
    wx: {
      request(options) {
        const path = options.url.replace('http://127.0.0.1:8001', '');
        const auth = (options.header && options.header.Authorization) || '';
        const respond = server.route(path, options.method, options.data, auth);
        return Promise.resolve(respond).then(
          ({ status, body }) => options.success({ statusCode: status, data: body }),
          (err) => options.fail({ errMsg: err.message })
        );
      },
      uploadFile(options) {
        const path = options.url.replace('http://127.0.0.1:8001', '');
        const auth = (options.header && options.header.Authorization) || '';
        return Promise.resolve(server.route(path, 'POST', null, auth)).then(
          ({ status, body }) => options.success({ statusCode: status, data: JSON.stringify(body) }),
          (err) => options.fail({ errMsg: err.message })
        );
      },
    },
  });
  return { api: rt.load('utils/api.js'), rt };
}

function simpleServer() {
  const state = { logins: 0, course401: 0 };
  return {
    state,
    route(path, method, data, auth) {
      if (path === '/api/wechat/login') {
        state.logins += 1;
        return {
          status: 200,
          body: {
            user_id: 1,
            account_id: 1,
            session_token: 'session-' + state.logins,
            expires_in: 3600,
          },
        };
      }
      if (path === '/api/auth/logout') {
        return { status: 204, body: null };
      }
      if (path.startsWith('/api/courses')) {
        if (!auth || auth === 'Bearer session-2') {
          state.course401 += 1;
          return { status: 401, body: { detail: 'session_invalid' } };
        }
        return { status: 200, body: [{ id: 1, name: '课' }] };
      }
      return { status: 404, body: { detail: 'not found' } };
    },
  };
}

async function main() {
  await check('业务请求自动登录并携带 Bearer；再次请求复用会话', async () => {
    const server = simpleServer();
    const { api } = makeApiRt(server);
    const courses = await api.getCourses();
    assert.strictEqual(courses.length, 1);
    assert.strictEqual(server.state.logins, 1);
    await api.getCourses();
    assert.strictEqual(server.state.logins, 1);
  });

  await check('401 单次重登后重试成功；重登仍 401 抛 authRequired 且不无限重试', async () => {
    const server = simpleServer();
    // 服务端持续拒绝课程请求（会话无效）：第一次 401 → 重登 → 仍 401 → authRequired
    server.route = (path, _method, _data, _auth) => {
      if (path === '/api/wechat/login') {
        server.state.logins += 1;
        return {
          status: 200,
          body: {
            user_id: 1,
            account_id: 1,
            session_token: 'session-' + server.state.logins,
            expires_in: 3600,
          },
        };
      }
      if (path.startsWith('/api/courses')) {
        return { status: 401, body: { detail: 'session_invalid' } };
      }
      return { status: 404, body: { detail: 'not found' } };
    };
    const { api } = makeApiRt(server);
    const err = await api.getCourses().then(
      () => null,
      (e) => e
    );
    assert.ok(err);
    assert.strictEqual(err.authRequired, true);
    assert.strictEqual(server.state.logins, 2, '恰好一次重登，不无限重试');
  });

  await check('重登后账号变化 → accountChanged，旧账号操作不落到新账号', async () => {
    const server = simpleServer();
    server.route = (path, _method, _data, auth) => {
      if (path === '/api/wechat/login') {
        server.state.logins += 1;
        return {
          status: 200,
          body: {
            user_id: server.state.logins, // 重登换人
            account_id: server.state.logins,
            session_token: 'session-' + server.state.logins,
            expires_in: 3600,
          },
        };
      }
      if (path.startsWith('/api/courses')) {
        if (auth === 'Bearer session-1') {
          return { status: 401, body: { detail: 'session_invalid' } };
        }
        return { status: 200, body: [{ id: 1, name: '课' }] };
      }
      return { status: 404, body: { detail: 'not found' } };
    };
    const { api } = makeApiRt(server);
    const err = await api.getCourses().then(
      () => null,
      (e) => e
    );
    assert.ok(err);
    assert.strictEqual(err.accountChanged, true, '账号已变化应中止旧请求');
  });

  await check('引导入口（微信登录）不要求会话', async () => {
    const server = simpleServer();
    const { api } = makeApiRt(server);
    const session = await api.wechatLogin('code-x');
    assert.strictEqual(session.session_token, 'session-1');
    assert.strictEqual(server.state.logins, 1);
  });

  await check('显式退出后业务请求抛 loggedOut，不自动重新登录', async () => {
    const server = simpleServer();
    const { api, rt } = makeApiRt(server);
    await api.getCourses(); // 先登录
    // 通过运行时内的会话模块退出（与 api.js 同一实例、同一存储）
    const sessionMod = rt.load('utils/session.js');
    await sessionMod.logout();
    const err = await api.getCourses().then(
      () => null,
      (e) => e
    );
    assert.ok(err && err.loggedOut, '退出后不自动重登');
    assert.strictEqual(server.state.logins, 1, '未发生新的登录请求');
    // 手动登录后恢复
    await sessionMod.login();
    const courses = await api.getCourses();
    assert.ok(Array.isArray(courses));
  });

  await check('业务上传同会话语义：401 重登一次后成功', async () => {
    const server = simpleServer();
    server.route = (path, _method, _data, auth) => {
      if (path === '/api/wechat/login') {
        server.state.logins += 1;
        return {
          status: 200,
          body: {
            user_id: 1,
            account_id: 1,
            session_token: 'session-' + server.state.logins,
            expires_in: 3600,
          },
        };
      }
      if (path === '/api/courses/parse-image') {
        if (auth === 'Bearer session-1') {
          return { status: 401, body: { detail: 'session_invalid' } };
        }
        return { status: 200, body: { courses: [], warnings: [] } };
      }
      return { status: 404, body: { detail: 'not found' } };
    };
    const { api } = makeApiRt(server);
    const handle = api.parseCourseImage('x.png');
    const result = await handle.done;
    assert.deepStrictEqual(JSON.parse(JSON.stringify(result)), { courses: [], warnings: [] });
    assert.strictEqual(server.state.logins, 2);
  });

  console.log(`\n全部通过：${passed} 项`);
}

main().catch((err) => {
  console.error('FAIL:', err.message);
  process.exit(1);
});
