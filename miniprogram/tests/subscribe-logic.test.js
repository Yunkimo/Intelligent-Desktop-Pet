// 状态和故障窗口回归；服务端行为另由真实 HTTP 集成覆盖。
const test = require('node:test');
const assert = require('node:assert/strict');
const { runtime } = require('./runtime');
const TASK = { id: 9, remind_at: '2040-01-01T08:00+08:00' };
function fixture() {
  let records = [];
  let dialogs = 0;
  let posts = 0;
  let logins = 0;
  const reminder = { id: 5, event_id: 'event-1', remind_at: '2040-01-01T00:00:00.000000+00:00' };
  const api = {
    baseUrl: 'http://localhost',
    wechatLogin: async () => {
      logins++;
      return { user_id: 1, session_token: 'test', expires_in: 7200 };
    },
    ensurePhoneReminder: async () => reminder,
    getWechatReminder: async () => ({ reminder }),
    getSubscriptions: async () => records,
    wechatSubscribe: async (payload) => {
      posts++;
      const record = {
        ...payload,
        choice: payload.result,
        status: payload.result === 'accept' ? 'pending' : 'rejected',
      };
      records = [record];
      return record;
    },
  };
  const rt = runtime({
    config: { subscribeTemplateId: 'test' },
    api,
    wx: {
      requestSubscribeMessage: ({ success }) => {
        dialogs++;
        success({ test: 'accept' });
      },
    },
  });
  const sub = rt.load('utils/subscribe.js');
  return {
    rt,
    sub,
    api,
    reminder,
    records: () => records,
    setRecords: (value) => {
      records = value;
    },
    dialogs: () => dialogs,
    posts: () => posts,
    logins: () => logins,
  };
}
test('UUID、会话临界期和非同意结果', () => {
  const { sub } = fixture();
  assert.match(sub.newRequestId(), /^[0-9a-f-]{36}$/);
  assert.notEqual(sub.newRequestId(), sub.newRequestId());
  assert.equal(sub.isSessionValid({ session_token: 'test', expires_at: 120000 }, 60000), false);
  assert.equal(sub.isSessionValid({ session_token: 'test', expires_at: 120001 }, 60000), true);
  assert.equal(sub.isSessionValid({}, 0), false);
  for (const choice of ['reject', 'ban', 'filter', 'unknown']) {
    assert.equal(sub.classifyResult(choice).ok, false);
  }
});
test('并发入口合并且授权在点击同步调用链触发', async () => {
  const f = fixture();
  const one = f.sub.subscribeTaskReminder(TASK);
  assert.equal(f.dialogs(), 1);
  const two = f.sub.subscribeTaskReminder(TASK);
  assert.equal(one, two);
  assert.equal((await one).status, 'pending');
  assert.equal(f.posts(), 1);
});
test('拒绝、取消和调用失败不误报成功', async () => {
  for (const choice of ['reject', 'ban', 'filter', null, 'error']) {
    const f = fixture();
    f.rt.wx.requestSubscribeMessage = ({ success, fail }) =>
      choice === null ? fail({ errMsg: 'cancel' }) : success({ test: choice });
    const result = await f.sub.subscribeTaskReminder(TASK);
    assert.equal(
      result.status,
      choice === null ? 'cancel' : choice === 'error' ? 'error' : 'rejected'
    );
    assert.equal(f.posts(), choice === null || choice === 'error' ? 0 : 1);
  }
});
test('缺模板和登录失败不登记', async () => {
  const rt = runtime();
  await assert.rejects(rt.load('utils/subscribe.js').subscribeTaskReminder(TASK), /模板/);
  const f = fixture();
  f.rt.wx.login = ({ fail }) => fail({});
  await assert.rejects(f.sub.subscribeTaskReminder(TASK), /登录失败/);
  assert.equal(f.posts(), 0);
});
test('已有记录每次查询：不依赖旧 done 缓存，也不重复登记', async () => {
  const f = fixture();
  await f.sub.subscribeTaskReminder(TASK);
  f.rt.storage.set('sub_flag_9', 'done');
  assert.equal((await f.sub.subscribeTaskReminder(TASK)).status, 'pending');
  assert.equal(f.posts(), 1);
  f.reminder.event_id = 'event-2';
  assert.equal((await f.sub.subscribeTaskReminder(TASK)).status, 'pending');
  assert.equal(f.posts(), 2);
});
test('任意 409 不算成功；rejected 冲突保持拒绝', async () => {
  const f = fixture();
  f.api.wechatSubscribe = async () => {
    f.setRecords([{ event_id: 'event-1', status: 'rejected' }]);
    throw Object.assign(new Error('conflict'), {
      statusCode: 409,
      code: 'reminder_already_registered',
    });
  };
  assert.equal((await f.sub.subscribeTaskReminder(TASK)).status, 'rejected');
  f.setRecords([]);
  f.api.wechatSubscribe = async () => {
    throw Object.assign(new Error('idempotency_conflict'), {
      statusCode: 409,
      code: 'idempotency_conflict',
    });
  };
  await assert.rejects(f.sub.subscribeTaskReminder(TASK), /idempotency_conflict/);
});
test('已有有效登记时再次拒绝，区分本次选择和旧登记状态', async () => {
  const f = fixture();
  await f.sub.subscribeTaskReminder(TASK);
  f.rt.wx.requestSubscribeMessage = ({ success }) => success({ test: 'reject' });
  const result = await f.sub.subscribeTaskReminder(TASK);
  assert.equal(result.status, 'choice-rejected');
  assert.match(result.message, /本次未同意/);
  assert.equal(f.posts(), 1);
});
test('提交后丢响应，模块重载后查询已发送状态，不再弹窗或提交', async () => {
  const f = fixture();
  const submit = f.api.wechatSubscribe;
  f.api.wechatSubscribe = async (payload) => {
    await submit(payload);
    throw new Error('response lost');
  };
  await assert.rejects(f.sub.subscribeTaskReminder(TASK), /待确认/);
  f.records()[0].status = 'sent';
  f.rt.cache.clear();
  const reloaded = f.rt.load('utils/subscribe.js');
  assert.equal((await reloaded.subscribeTaskReminder(TASK)).status, 'sent');
  assert.equal(f.posts(), 1);
  assert.equal(f.dialogs(), 1);
});
test('提交前断网，重进复用 request_id；改期不会重放旧授权', async () => {
  const f = fixture();
  const payloads = [];
  const submit = f.api.wechatSubscribe;
  f.api.wechatSubscribe = async (payload) => {
    payloads.push(payload.request_id);
    if (payloads.length === 1) {
      throw new Error('offline');
    }
    return submit(payload);
  };
  await assert.rejects(f.sub.subscribeTaskReminder(TASK), /待确认/);
  await f.sub.subscribeTaskReminder(TASK);
  assert.equal(payloads[0], payloads[1]);
  f.setRecords([]);
  f.api.wechatSubscribe = async () => {
    throw new Error('lost');
  };
  await assert.rejects(f.sub.subscribeTaskReminder(TASK));
  f.reminder.event_id = 'changed';
  assert.equal((await f.sub.subscribeTaskReminder(TASK)).status, 'changed');
});
test('创建丢响应后改期，旧选择不会应用于新时间', async () => {
  const f = fixture();
  const ensure = f.api.ensurePhoneReminder;
  f.api.ensurePhoneReminder = async () => {
    throw new Error('lost');
  };
  await assert.rejects(f.sub.subscribeTaskReminder(TASK));
  f.api.ensurePhoneReminder = ensure;
  f.reminder.remind_at = '2040-01-02T00:00:00Z';
  assert.equal((await f.sub.subscribeTaskReminder(TASK)).status, 'changed');
  assert.equal(f.posts(), 0);
});
test('401 只重登录一次；账号变化禁止重放旧操作', async () => {
  const f = fixture();
  f.api.ensurePhoneReminder = async () => {
    throw Object.assign(new Error('401'), { statusCode: 401 });
  };
  await assert.rejects(f.sub.subscribeTaskReminder(TASK));
  assert.equal(f.logins(), 2);
  const g = fixture();
  g.api.wechatSubscribe = async () => {
    throw new Error('lost');
  };
  await assert.rejects(g.sub.subscribeTaskReminder(TASK));
  g.api.getWechatReminder = async () => {
    throw Object.assign(new Error('401'), { statusCode: 401 });
  };
  g.api.wechatLogin = async () => ({ user_id: 2, session_token: 'other', expires_in: 7200 });
  await assert.rejects(g.sub.subscribeTaskReminder(TASK), /账号已变化/);
});
test('failed/uncertain/sending 不自动重发', async () => {
  for (const status of ['failed', 'uncertain', 'sending']) {
    const f = fixture();
    f.setRecords([{ event_id: 'event-1', status }]);
    assert.equal((await f.sub.subscribeTaskReminder(TASK)).status, status);
    assert.equal(f.posts(), 0);
  }
});
test('UTC、旧格式、跨日和输入偏移', () => {
  const dt = runtime().load('utils/datetime.js');
  assert.equal(dt.reminderParts('2040-01-01T02:00:00.000000Z').time, '10:00');
  assert.equal(dt.reminderParts('2039-12-31T17:00:00Z').date, '2040-01-01');
  assert.equal(dt.reminderParts('2040-01-01T01:00').time, '01:00');
  assert.equal(dt.reminderInput('2040-01-01', '10:00'), '2040-01-01T10:00:00+08:00');
});
