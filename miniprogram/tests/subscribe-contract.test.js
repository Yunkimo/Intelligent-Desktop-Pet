// 由 scripts/check_c3_integration.py 启动真实后端；这里只模拟 wx 适配层。
const assert = require('node:assert/strict');
const { runtime } = require('./runtime');
const baseUrl = 'http://127.0.0.1:' + process.env.C3_TEST_PORT;
const token = process.env.API_TOKEN;
if (!process.env.C3_TEST_PORT) {
  throw new Error('请运行 python scripts/check_c3_integration.py');
}
let choice = 'accept';
let dialogs = 0;
let dropPath;
let remainingDrops = 0;
let captured = [];
const rt = runtime({
  config: { baseUrl, apiKey: token, subscribeTemplateId: 'test' },
  wx: {
    requestSubscribeMessage: ({ success }) => {
      dialogs++;
      success({ test: choice });
    },
    request: (options) => {
      fetch(options.url, {
        method: options.method,
        headers: options.header,
        body: options.data ? JSON.stringify(options.data) : undefined,
      })
        .then(async (response) => {
          const text = await response.text();
          captured.push({
            path: new URL(options.url).pathname,
            body: options.data,
            status: response.status,
          });
          if (remainingDrops && new URL(options.url).pathname === dropPath && response.ok) {
            remainingDrops--;
            options.fail({ errMsg: 'response lost after server commit' });
          } else {
            options.success({ statusCode: response.status, data: text ? JSON.parse(text) : null });
          }
        })
        .catch((error) => options.fail({ errMsg: error.message }));
    },
    showToast: () => {},
    showLoading: () => {},
    hideLoading: () => {},
  },
});
const api = rt.load('utils/api.js');
let sub = rt.load('utils/subscribe.js');
let passed = 0;
async function check(name, fn) {
  await fn();
  passed++;
  console.log('PASS ' + name);
}
async function raw(path, method = 'GET', body, session) {
  const response = await fetch(baseUrl + path, {
    method,
    headers: {
      'X-API-Key': token,
      'Content-Type': 'application/json',
      ...(session ? { Authorization: 'Bearer ' + session } : {}),
    },
    body: body ? JSON.stringify(body) : undefined,
  });
  const text = await response.text();
  return { status: response.status, data: text ? JSON.parse(text) : null };
}
async function task(time = '2000-01-01T08:00+08:00') {
  return api.createTask({ title: 'C3 集成回归', remind_at: time, note: '当前内容' });
}
async function reminder(t) {
  return (await api.getReminders()).find((r) => r.task_id === t.id);
}
async function state(r) {
  return (await raw('/api/reminders/' + r.id + '/delivery')).data;
}
async function tick() {
  return (await raw('/__test__/tick', 'POST')).data;
}
async function main() {
  await check('真实登记、拒绝两次后同意、409 不变成功', async () => {
    const t = await task();
    choice = 'reject';
    assert.equal((await sub.subscribeTaskReminder(t)).status, 'rejected');
    assert.equal((await sub.subscribeTaskReminder(t)).status, 'rejected');
    choice = 'accept';
    assert.equal((await sub.subscribeTaskReminder(t)).status, 'pending');
    const rows = (await state(await reminder(t))).wechat;
    assert.equal(rows.length, 1);
    assert.equal(rows[0].choice, 'accept');
    await api.deleteTask(t.id);
  });
  await check('登记提交后丢响应、调度后重进，只有一次平台调用', async () => {
    const t = await task();
    const before = (await tick()).sent.length;
    dropPath = '/api/wechat/subscribe';
    remainingDrops = 1;
    await assert.rejects(sub.subscribeTaskReminder(t), /待确认/);
    const r = await reminder(t);
    const event = (await state(r)).event_id;
    const dialogCount = dialogs;
    assert.equal((await tick()).sent.length, before + 1);
    rt.cache.clear();
    sub = rt.load('utils/subscribe.js');
    assert.equal((await sub.subscribeTaskReminder(t)).status, 'sent');
    assert.equal(dialogs, dialogCount);
    assert.equal((await state(r)).event_id, event);
    assert.equal((await tick()).sent.length, before + 1);
    await api.deleteTask(t.id);
  });
  await check('创建提交后丢响应重试和两个并发入口不会重复创建', async () => {
    const t = await task();
    dropPath = '/api/wechat/reminders';
    remainingDrops = 1;
    await assert.rejects(sub.subscribeTaskReminder(t));
    assert.equal((await sub.subscribeTaskReminder(t)).status, 'pending');
    assert.equal((await api.getReminders()).filter((r) => r.task_id === t.id).length, 1);
    await api.deleteTask(t.id);
    const concurrent = await task();
    await Promise.all([
      sub.subscribeTaskReminder(concurrent),
      sub.subscribeTaskReminder(concurrent),
    ]);
    assert.equal((await api.getReminders()).filter((r) => r.task_id === concurrent.id).length, 1);
    await api.deleteTask(concurrent.id);
  });
  await check('等价 UTC 写入不重置事件或完成状态', async () => {
    const t = await task();
    await sub.subscribeTaskReminder(t);
    const r = await reminder(t);
    const before = (await state(r)).event_id;
    await tick();
    await api.updateTask(t.id, { remind_at: '2000-01-01T00:00:00.000000Z' });
    await sub.subscribeTaskReminder(t);
    assert.equal((await state(r)).event_id, before);
    assert.equal((await reminder(t)).done, 1);
    await api.deleteTask(t.id);
  });
  await check('页面真实保存改期、清除及删除同步使旧提醒失效', async () => {
    const t = await task();
    await sub.subscribeTaskReminder(t);
    const r = await reminder(t);
    const page = rt.loadPage('pages/task/task.js');
    page.data.form = {
      id: t.id,
      title: '改期',
      note: '',
      due_at: '',
      remind_date: '2041-01-01',
      remind_time: '10:00',
    };
    await page.submit();
    assert.equal((await state(r)).wechat[0].status, 'cancelled');
    assert.equal((await reminder(t)).remind_at.slice(0, 16), '2041-01-01T02:00');
    const count = (await tick()).sent.length;
    assert.equal((await tick()).sent.length, count);
    await api.updateTask(t.id, { remind_at: null });
    assert.equal(await reminder(t), undefined);
    await api.deleteTask(t.id);
  });
  await check('服务端改期后本地 done 不遮蔽当前事件', async () => {
    const t = await task();
    await sub.subscribeTaskReminder(t);
    rt.storage.set('sub_flag_' + t.id, 'done');
    await api.updateTask(t.id, { remind_at: '2041-02-02T10:00+08:00' });
    const latest = (await api.getTasks()).find((item) => item.id === t.id);
    assert.equal((await sub.subscribeTaskReminder(latest)).status, 'pending');
    const statuses = (await state(await reminder(t))).wechat;
    assert.equal(statuses.length, 2);
    assert.equal(statuses[0].status, 'cancelled');
    await api.deleteTask(t.id);
  });
  await check('会话撤销自动重登录一次，其他账号和伪造身份被拒绝', async () => {
    const t = await task();
    await sub.subscribeTaskReminder(t);
    const r = await reminder(t);
    await api.wechatLogin('alice'); // 撤销前端旧会话。
    const count = captured.filter((r) => r.path === '/api/wechat/login').length;
    assert.equal((await sub.subscribeTaskReminder(t)).status, 'pending');
    assert.equal(captured.filter((r) => r.path === '/api/wechat/login').length, count + 1);
    const bob = await api.wechatLogin('bob');
    assert.equal(
      (await raw('/api/wechat/reminders/' + r.id, 'GET', null, bob.session_token)).status,
      404
    );
    assert.equal(
      (await raw('/api/wechat/reminders', 'POST', { task_id: t.id, user_id: 1 }, bob.session_token))
        .status,
      422
    );
    await api.deleteTask(t.id);
  });
  await check('真实今日页面 UTC 转换覆盖 10:00、凌晨 01:00', async () => {
    const dt = rt.load('utils/datetime.js');
    const today = dt.reminderParts(new Date().toISOString()).date;
    const tasks = [await task(today + 'T10:00+08:00'), await task(today + 'T01:00+08:00')];
    for (const t of tasks) {
      await sub.subscribeTaskReminder(t);
    }
    const page = rt.loadPage('pages/index/index.js');
    await page.loadToday();
    const times = tasks.map((t) => page.data.reminders.find((r) => r.task_id === t.id).remindTime);
    assert.equal(times[0], '10:00');
    assert.equal(times[1], '01:00');
    for (const t of tasks) {
      await api.deleteTask(t.id);
    }
  });
  await check('真实 WS 阳性对照：pc 有事件，phone 仅微信渠道', async () => {
    const received = [];
    const socket = new WebSocket(baseUrl.replace('http:', 'ws:') + '/ws?token=' + token);
    await new Promise((resolve, reject) => {
      const timer = setTimeout(() => reject(new Error('WS timeout')), 3000);
      socket.addEventListener(
        'open',
        () => {
          clearTimeout(timer);
          resolve();
        },
        { once: true }
      );
      socket.addEventListener('error', reject, { once: true });
    });
    socket.addEventListener('message', (event) => received.push(JSON.parse(event.data)));
    try {
      const t = await task();
      await sub.subscribeTaskReminder(t);
      const phone = await reminder(t);
      const pc = await api.createReminder({
        title: 'WS 对照',
        remind_at: t.remind_at,
        channel: 'pc',
      });
      const count = (await tick()).sent.length;
      await new Promise((resolve) => setTimeout(resolve, 100));
      assert.ok(received.some((e) => e.type === 'reminder.due' && e.data.id === pc.id));
      assert.ok(!received.some((e) => e.type === 'reminder.due' && e.data.id === phone.id));
      assert.ok(count > 0);
      await api.deleteTask(t.id);
      await api.deleteReminder(pc.id);
    } finally {
      socket.close();
    }
  });
  await check('消息目标不含凭据；详情页重新读取和资源删除反馈', async () => {
    const t = await task();
    await sub.subscribeTaskReminder(t);
    const r = await reminder(t);
    const sent = (await tick()).sent;
    assert.ok(sent.some((s) => s.page === 'pages/reminder/reminder?reminder_id=' + r.id));
    const page = rt.loadPage('pages/reminder/reminder.js');
    page.onLoad({ reminder_id: String(r.id) });
    await page.onShow();
    assert.equal(page.data.task.title, t.title);
    await api.updateTask(t.id, { title: '最新标题' });
    await page.onShow();
    assert.equal(page.data.task.title, '最新标题');
    await api.deleteTask(t.id);
    await page.onShow();
    assert.match(page.data.error, /已删除/);
    page.onLoad({ reminder_id: 'invalid' });
    await page.onShow();
    assert.match(page.data.error, /无效/);
  });
  console.log('C3 real-backend integration passed: ' + passed);
}
main().catch((error) => {
  console.error(error);
  process.exitCode = 1;
});
