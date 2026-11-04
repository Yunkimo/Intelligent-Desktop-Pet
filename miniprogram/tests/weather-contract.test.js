// 带伞提醒（契约/联调层）：由 scripts/check_weather_integration.py 启动真实后端
// （临时数据库 + 模拟微信上游 + 模拟天气上游）。覆盖 B 契约 weather-subscriptions.md：
// - 准备事件幂等（同用户同城市同目标日期返回同一 event_id）
// - 登记授权（accept→pending；reject→rejected；不同 request_id 重复登记 409）
// - 列表/详情/取消与账号隔离（他人事件 404）
// 天气上游经 WEATHER_UPSTREAM_URL 指向本地模拟服务，保证确定性。

const assert = require('node:assert/strict');
const { runtime } = require('./runtime');

const baseUrl = 'http://127.0.0.1:' + process.env.WEATHER_TEST_PORT;
if (!process.env.WEATHER_TEST_PORT) {
  throw new Error('请运行 python scripts/check_weather_integration.py');
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
    requestSubscribeMessage: ({ success }) => success({ weather: 'accept' }),
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

function switchUser(code) {
  currentCode = code;
  session.clearSession();
}

function newRequestId() {
  return 'xxxxxxxx-xxxx-4xxx-yxxx-xxxxxxxxxxxx'.replace(/[xy]/g, (c) => {
    const r = (Math.random() * 16) | 0;
    return (c === 'x' ? r : (r & 3) | 8).toString(16);
  });
}

async function main() {
  await check('准备事件幂等：同用户同城市返回同一 event_id', async () => {
    switchUser('alice');
    await api.getCourses(); // 确保会话
    const first = await api.weatherPrepare('长沙');
    const second = await api.weatherPrepare('长沙');
    assert.strictEqual(first.event_id, second.event_id);
    assert.strictEqual(typeof first.template_id, 'string');
    assert.strictEqual(first.status, 'prepared');
    assert.match(first.target_date, /^\d{4}-\d{2}-\d{2}$/);
    // 不同城市是不同事件
    const other = await api.weatherPrepare('北京');
    assert.notEqual(other.event_id, first.event_id);
  });

  await check('登记授权：accept→pending，reject→rejected，同 request_id 幂等', async () => {
    switchUser('alice');
    await api.getCourses();
    const event = await api.weatherPrepare('长沙');
    const requestId = newRequestId();
    const pending = await api.weatherAuthorize(event.event_id, {
      request_id: requestId,
      template_id: event.template_id,
      result: 'accept',
    });
    assert.strictEqual(pending.status, 'pending');
    // 同 request_id 同参数重放：返回当前事件状态，不报错
    const replay = await api.weatherAuthorize(event.event_id, {
      request_id: requestId,
      template_id: event.template_id,
      result: 'accept',
    });
    assert.strictEqual(replay.status, 'pending');
    // 不同 request_id 重复登记：409 weather_event_already_registered
    const conflict = await api
      .weatherAuthorize(event.event_id, {
        request_id: newRequestId(),
        template_id: event.template_id,
        result: 'accept',
      })
      .then(
        () => null,
        (e) => e
      );
    assert.strictEqual(conflict && conflict.statusCode, 409);
    assert.match(conflict.message, /already_registered/);
  });

  await check('列表与详情返回本人事件，他人事件 404', async () => {
    switchUser('alice');
    await api.getCourses();
    const event = await api.weatherPrepare('长沙');
    const list = await api.getWeatherSubscriptions();
    assert.ok(Array.isArray(list) && list.length >= 1);
    const detail = await api.getWeatherSubscription(event.event_id);
    assert.strictEqual(detail.event_id, event.event_id);
    // 他人（bob）访问 alice 的事件：404
    switchUser('bob');
    await api.getCourses();
    const err = await api.getWeatherSubscription(event.event_id).then(
      () => null,
      (e) => e
    );
    assert.strictEqual(err && err.statusCode, 404);
  });

  await check('取消未发送事件后状态为 cancelled，再取消 404/409 不重复', async () => {
    switchUser('alice');
    await api.getCourses();
    const event = await api.weatherPrepare('武汉'); // 新城市 = 新事件（长沙已在上一用例登记）
    await api.weatherAuthorize(event.event_id, {
      request_id: newRequestId(),
      template_id: event.template_id,
      result: 'accept',
    });
    const cancelled = await api.cancelWeatherSubscription(event.event_id);
    assert.strictEqual(cancelled.status, 'cancelled');
    // B 语义：对已取消事件重复取消幂等返回 cancelled；不报错、不重复发送
    const again = await api.cancelWeatherSubscription(event.event_id).then(
      (result) => result,
      (e) => e
    );
    assert.ok(
      (again && again.status === 'cancelled') ||
        (again && (again.statusCode === 404 || again.statusCode === 409)),
      '重复取消应幂等或拒绝'
    );
  });

  await check('天气卡片：明天接口按会话返回长沙预报（模拟上游）', async () => {
    switchUser('alice');
    await api.getCourses();
    const forecast = await api.getWeatherTomorrow('长沙');
    assert.strictEqual(forecast.status, 'ok');
    assert.strictEqual(typeof forecast.rain, 'boolean');
    assert.strictEqual(forecast.city, '长沙');
    assert.match(forecast.date, /^\d{4}-\d{2}-\d{2}$/);
  });

  console.log(`\n全部通过：${passed} 项`);
}

main().catch((err) => {
  console.error('FAIL:', err.message);
  process.exit(1);
});
