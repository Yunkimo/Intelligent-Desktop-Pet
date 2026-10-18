// C3：点击同步授权；恢复复用原请求，状态以服务端为准。
const api = require('./api');
const { reminderDate } = require('./datetime');
let config = {};
try {
  config = require('../config');
} catch (_) {
  /* 页面提示缺配置 */
}
const SESSION_KEY = 'wechat_session:' + api.baseUrl;
const inFlight = new Map();
let loginFlight;
function getTemplateId() {
  return config.subscribeTemplateId || '';
}
function newRequestId() {
  return 'xxxxxxxx-xxxx-4xxx-yxxx-xxxxxxxxxxxx'.replace(/[xy]/g, (c) => {
    const r = (Math.random() * 16) | 0;
    return (c === 'x' ? r : (r & 3) | 8).toString(16);
  });
}
function isSessionValid(session, now) {
  return !!(session && session.session_token && now < session.expires_at - 60000);
}
function classifyResult(result) {
  return result === 'accept'
    ? { ok: true, message: '已登记订阅，发送结果以服务端和微信为准' }
    : {
        ok: false,
        message: ['reject', 'ban', 'filter'].includes(result)
          ? '未授权订阅，不影响课表和日程功能'
          : '',
      };
}
async function ensureSession() {
  const cached = wx.getStorageSync(SESSION_KEY);
  if (isSessionValid(cached, Date.now())) {
    return cached;
  }
  if (!loginFlight) {
    loginFlight = (async () => {
      const result = await new Promise((resolve, reject) =>
        wx.login({
          success: resolve,
          fail: () => reject(new Error('微信登录失败，请检查网络后重试')),
        })
      );
      if (!result.code) {
        throw new Error('微信未返回登录 code');
      }
      const response = await api.wechatLogin(result.code);
      const session = { ...response, expires_at: Date.now() + response.expires_in * 1000 };
      wx.setStorageSync(SESSION_KEY, session);
      return session;
    })().finally(() => {
      loginFlight = null;
    });
  }
  return loginFlight;
}
async function withSession(action, expectedUser) {
  for (let attempt = 0; attempt < 2; attempt += 1) {
    const session = await ensureSession();
    if (expectedUser != null && expectedUser !== session.user_id) {
      throw new Error('登录账号已变化，请返回日程页重新操作');
    }
    try {
      return await action(session);
    } catch (error) {
      if (error.statusCode !== 401 || attempt === 1) {
        throw error;
      }
      wx.setStorageSync(SESSION_KEY, { ...session, expires_at: 0 });
    }
  }
}
function requestSubscribe(templateId) {
  return new Promise((resolve) =>
    wx.requestSubscribeMessage({
      tmplIds: [templateId],
      success: (result) => resolve(result[templateId] || 'reject'),
      fail: (error) => resolve(error && /cancel/.test(error.errMsg) ? null : 'error'),
    })
  );
}
function operationKey(taskId, userId) {
  return 'wechat_pending:' + api.baseUrl + ':' + userId + ':' + taskId;
}
function resultFor(record) {
  const messages = {
    pending: '已登记订阅，等待到期发送',
    retry: '服务端等待有限重试，请勿重复订阅',
    sending: '正在发送，请稍后查询',
    sent: '微信平台已受理，请在手机查看消息',
    rejected: '未授权订阅，可再次点击同意',
    cancelled: '旧提醒已失效，请重新订阅当前日程',
    failed: '发送失败，请检查配置或修改提醒时间后重新订阅',
    uncertain: '发送结果待确认，请勿重复发送，请联系服务端核查',
  };
  return { status: record.status, message: messages[record.status] || '状态待确认' };
}
function resultForChoice(record, choice) {
  const result = resultFor(record);
  if (choice !== 'accept' && record.choice === 'accept') {
    return { status: 'choice-rejected', message: '本次未同意；已有提醒状态：' + result.message };
  }
  return result;
}
async function subscriptionStates() {
  if (!wx.getStorageSync(SESSION_KEY)) {
    return {};
  }
  const rows = await withSession((s) => api.getWechatReminders(s.session_token));
  const states = {};
  for (const row of rows) {
    states[row.task_id] = row.status ? resultFor(row).message : '当前事件未订阅';
  }
  return states;
}
async function finishOperation(task, operation, key) {
  const call = (action) => withSession(action, operation.userId);
  let reminder;
  if (operation.payload) {
    const detail = await call((s) =>
      api.getWechatReminder(operation.payload.reminder_id, s.session_token)
    );
    reminder = detail.reminder;
    if (reminder.event_id !== operation.payload.event_id) {
      wx.removeStorageSync(key);
      return { status: 'changed', message: '提醒已经改期，旧授权不再提交，请重新点击订阅' };
    }
  } else {
    reminder = await call((s) => api.ensurePhoneReminder(task.id, s.session_token));
    if (reminderDate(reminder.remind_at).getTime() !== reminderDate(operation.taskTime).getTime()) {
      wx.removeStorageSync(key);
      return { status: 'changed', message: '日程已改期，请刷新后重新订阅' };
    }
    operation.payload = {
      reminder_id: reminder.id,
      event_id: reminder.event_id,
      request_id: operation.requestId,
      template_id: operation.templateId,
      result: operation.choice,
    };
    wx.setStorageSync(key, operation);
  }
  const records = await call((s) => api.getSubscriptions(reminder.id, s.session_token));
  const current = records.find((record) => record.event_id === reminder.event_id);
  if (current && (current.request_id === operation.requestId || current.status !== 'rejected')) {
    wx.removeStorageSync(key);
    return resultForChoice(current, operation.choice);
  }
  if (reminder.done) {
    wx.removeStorageSync(key);
    return { status: 'done', message: '该提醒已结束，需要新提醒时请修改提醒时间' };
  }
  try {
    const record = await call((s) => api.wechatSubscribe(operation.payload, s.session_token));
    wx.removeStorageSync(key);
    return resultFor(record);
  } catch (error) {
    if (error.statusCode === 409) {
      const latest = await call((s) => api.getSubscriptions(reminder.id, s.session_token));
      const matched = latest.find((record) => record.event_id === operation.payload.event_id);
      wx.removeStorageSync(key);
      if (error.code === 'reminder_already_registered' && matched) {
        return resultForChoice(matched, operation.choice);
      }
    } else if (error.statusCode >= 400 && error.statusCode < 500) {
      wx.removeStorageSync(key);
    }
    throw error;
  }
}
function subscribeTaskReminder(task) {
  if (inFlight.has(task.id)) {
    return inFlight.get(task.id);
  }
  const run = (async () => {
    const templateId = getTemplateId();
    if (!templateId) {
      throw new Error('未配置订阅模板 ID，请填写 subscribeTemplateId');
    }
    if (!task.remind_at) {
      throw new Error('请先设置日程提醒时间');
    }
    const cached = wx.getStorageSync(SESSION_KEY);
    const cachedKey = cached && operationKey(task.id, cached.user_id);
    let operation = cachedKey && wx.getStorageSync(cachedKey);
    if (!operation) {
      // 点击同步调用链触发；页面加载和网络恢复不自动弹窗。
      const choice = await requestSubscribe(templateId);
      if (choice === null) {
        return { status: 'cancel', message: '' };
      }
      if (!['accept', 'reject', 'ban', 'filter'].includes(choice)) {
        return { status: 'error', message: '授权调用失败，请重试' };
      }
      const session = await ensureSession();
      operation = {
        choice,
        templateId,
        taskTime: task.remind_at,
        userId: session.user_id,
        requestId: newRequestId(),
      };
    }
    const key = operationKey(task.id, operation.userId);
    wx.setStorageSync(key, operation);
    try {
      return await finishOperation(task, operation, key);
    } catch (error) {
      if (error.statusCode >= 400 && error.statusCode < 500) {
        wx.removeStorageSync(key);
        throw error;
      }
      throw new Error('处理结果待确认，恢复网络后再次点击将查询原记录；' + error.message);
    }
  })();
  inFlight.set(task.id, run);
  const release = () => {
    if (inFlight.get(task.id) === run) {
      inFlight.delete(task.id);
    }
  };
  run.then(release, release);
  return run;
}
module.exports = {
  getTemplateId,
  newRequestId,
  isSessionValid,
  classifyResult,
  subscribeTaskReminder,
  withSession,
  resultFor,
  subscriptionStates,
};
