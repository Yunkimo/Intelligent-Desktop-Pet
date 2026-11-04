// 带伞提醒（逻辑层）：驱动真实 utils/weather.js。
// - 城市偏好按账号隔离、规范化与默认值
// - 订阅状态→文案与可再订阅判定（B 契约 weather-subscriptions.md）
// - 天气卡片文案：rain=true/false/unknown 三种形态
// 由 tests/run-tests.js 以独立进程运行（node tests/weather-logic.test.js）。

const assert = require('assert');
const { runtime } = require('./runtime');

let passed = 0;
function check(name, fn) {
  fn();
  passed += 1;
  console.log('PASS', name);
}

const rt = runtime();
const weather = rt.load('utils/weather.js');
const session = rt.load('utils/session.js');

function main() {
  check('默认城市为长沙，规范化去空白且限长', () => {
    assert.strictEqual(weather.getSavedCity(), '长沙');
    assert.strictEqual(weather.normalizeCity('  北京  '), '北京');
    assert.strictEqual(weather.normalizeCity(''), null);
    assert.strictEqual(weather.normalizeCity('x'.repeat(200)).length, 80);
  });

  check('城市偏好按账号隔离保存', () => {
    // 未登录（本地键）
    weather.saveCity('上海');
    assert.strictEqual(weather.getSavedCity(), '上海');
    // 账号 A：保存后只影响 A 的键
    session.setApi({
      baseUrl: 'http://test',
      wechatLogin: async () => ({
        session_token: 'a',
        expires_in: 3600,
        user_id: 1,
        account_id: 1,
      }),
      authLogout: async () => {},
    });
    rt.wx.setStorageSync('wechat_session:http://test', {
      session_token: 'a',
      expires_at: Date.now() + 3600000,
      user_id: 1,
      account_id: 1,
    });
    weather.saveCity('广州');
    assert.strictEqual(weather.getSavedCity(), '广州');
    assert.strictEqual(rt.storage.get('weather_city:1'), '广州');
    // 账号 B 无偏好 → 回默认
    rt.wx.setStorageSync('wechat_session:http://test', {
      session_token: 'b',
      expires_at: Date.now() + 3600000,
      user_id: 2,
      account_id: 2,
    });
    assert.strictEqual(weather.getSavedCity(), '长沙');
  });

  check('订阅状态文案覆盖 B 契约全部状态', () => {
    const cases = {
      prepared: '待授权',
      pending: '已授权，今晚判断天气',
      checking: '正在检查天气',
      retry_weather: '天气暂不可用，稍后重查',
      sending: '微信发送中',
      retry: '发送重试中',
      sent: '已发送，请查看微信',
      no_rain: '本次无降水，不发送',
      rejected: '未取得授权',
      cancelled: '已取消',
      expired: '已过期',
      failed: '发送失败',
      uncertain: '发送结果待核实',
    };
    Object.entries(cases).forEach(([status, text]) => {
      assert.strictEqual(weather.statusText(status), text, status);
    });
    assert.strictEqual(weather.statusText('未知状态'), '未知状态');
    assert.strictEqual(weather.statusText(null), '');
  });

  check('可再订阅判定：未订阅/prepared/rejected/cancelled 才引导授权', () => {
    [null, 'prepared', 'rejected', 'cancelled'].forEach((status) => {
      assert.strictEqual(weather.canSubscribe(status), true, String(status));
    });
    [
      'pending',
      'checking',
      'retry_weather',
      'sending',
      'retry',
      'sent',
      'no_rain',
      'expired',
      'failed',
      'uncertain',
    ].forEach((status) => {
      assert.strictEqual(weather.canSubscribe(status), false, status);
    });
  });

  check('「明天」标签与天气卡片文案三种形态', () => {
    assert.strictEqual(weather.tomorrowLabel('2026-11-05'), '明天（11-05）');
    assert.strictEqual(weather.tomorrowLabel(''), '明天');
    assert.strictEqual(weather.tomorrowLabel('bad'), 'bad');
    assert.strictEqual(
      weather.weatherCardText({ status: 'ok', rain: true, desc: '可能有雨' }).headline,
      '明天可能有降水，记得带伞'
    );
    assert.strictEqual(
      weather.weatherCardText({ status: 'ok', rain: false }).headline,
      '明天暂无降水提示'
    );
    assert.strictEqual(weather.weatherCardText({ status: 'unknown' }).headline, '天气暂不可用');
    assert.strictEqual(weather.weatherCardText(null).headline, '天气暂不可用');
  });

  console.log(`\n全部通过：${passed} 项`);
}

main();
