// 订阅提醒流程（C3）：登录 → 创建/复用 phone 提醒 → 用户授权 → 后端登记。
// 契约见 docs/b3-wechat.md（后端 /api/wechat/*，B3 实现于 PR #29）：
// - 登录 code 由 wx.login 获取，会话 token 只存本地
// - 授权必须由用户真实点击触发（wx.requestSubscribeMessage 一次性订阅）
// - accept 只代表登记意图，实际权限由微信平台最终判断；拒绝不妨碍基本课表功能
// - 订阅模板 ID 需在微信公众平台申请后填入 config.js；未配置时直接提示，不发起授权

const api = require('./api');

// ===== 集中配置 =====
const SESSION_KEY = 'wechat_session';
const SUB_FLAG_PREFIX = 'sub_flag_'; // 每任务的本机订阅状态提示（业务状态以服务端为准）
const SESSION_SKEW_SECONDS = 60; // 会话提前过期余量，避免临界期请求被拒
// ====================

let config = {};
try {
  config = require('../config');
} catch (err) {
  /* config.js 缺失时订阅功能不可用，由 getTemplateId 提示 */
}

/** 订阅模板 ID（用户需在微信公众平台申请模板后填入 config.js）。 */
function getTemplateId() {
  return config.subscribeTemplateId || '';
}

/** 生成 request_id（UUID v4；每次新的授权点击生成，网络重试复用同一个）。 */
function newRequestId() {
  return 'xxxxxxxx-xxxx-4xxx-yxxx-xxxxxxxxxxxx'.replace(/[xy]/g, (c) => {
    const r = (Math.random() * 16) | 0;
    const v = c === 'x' ? r : (r & 0x3) | 0x8;
    return v.toString(16);
  });
}

/** 会话是否仍有效（存储的是毫秒时间戳）。 */
function isSessionValid(session, now) {
  return !!(
    session &&
    session.session_token &&
    session.expires_at &&
    now < session.expires_at - SESSION_SKEW_SECONDS * 1000
  );
}

/** 授权结果分类：accept 之外一律不声称订阅成功。 */
function classifyResult(result) {
  if (result === 'accept') {
    return { ok: true, message: '已登记订阅，到期将通过微信提醒' };
  }
  if (result === 'reject' || result === 'ban' || result === 'filter') {
    return { ok: false, message: '未授权订阅（不影响课表功能）' };
  }
  return { ok: false, message: '' };
}

/** 确保微信登录会话有效；返回会话对象 { session_token, user_id, expires_at }。 */
async function ensureSession() {
  const stored = wx.getStorageSync(SESSION_KEY);
  if (isSessionValid(stored, Date.now())) {
    return stored;
  }
  const res = await new Promise((resolve, reject) => {
    wx.login({
      success: resolve,
      fail: (err) => reject(new Error(`登录失败，请检查网络后重试（${err && err.errMsg ? err.errMsg : '微信登录不可用'}）`)),
    });
  });
  const data = await api.wechatLogin(res.code);
  const session = {
    session_token: data.session_token,
    user_id: data.user_id,
    expires_at: Date.now() + (data.expires_in || 7200) * 1000,
  };
  wx.setStorageSync(SESSION_KEY, session);
  return session;
}

/** 找到或创建该任务对应的 phone 提醒（服务端为准，避免重复创建）。

任务编辑后提醒时间可能已变化：按 B3 契约更新提醒（修改会取消旧待发授权，
需重新登记）。 */
async function ensurePhoneReminder(task, session) {
  const reminders = await api.getReminders();
  const existing = reminders.find(
    (r) => r.task_id === task.id && r.channel === 'phone' && r.wechat_user_id === session.user_id
  );
  if (existing) {
    if (existing.remind_at !== task.remind_at) {
      await api.updateReminder(existing.id, {
        title: task.title,
        body: task.note || '',
        remind_at: task.remind_at,
      });
    }
    return existing.id;
  }
  const created = await api.createReminder({
    title: task.title,
    body: task.note || '',
    remind_at: task.remind_at,
    channel: 'phone',
    wechat_user_id: session.user_id,
    task_id: task.id,
  });
  return created.id;
}

/** 查询微信记住的模板授权设置（accept/reject/ban/filter 或 undefined=未记录）。 */
function getRememberedSetting(templateId) {
  return new Promise((resolve) => {
    if (!wx.getSetting) {
      resolve(undefined);
      return;
    }
    wx.getSetting({
      withSubscriptions: true,
      success: (res) => {
        const settings = (res.subscriptionsSetting && res.subscriptionsSetting.itemSettings) || {};
        resolve(settings[templateId]);
      },
      fail: () => resolve(undefined),
    });
  });
}

/** 触发微信一次性订阅授权；用户关闭弹窗（cancel）返回 null。 */
function requestSubscribe(templateId) {
  return new Promise((resolve) => {
    wx.requestSubscribeMessage({
      tmplIds: [templateId],
      success: (res) => {
        resolve(res[templateId] || 'reject');
      },
      fail: (err) => {
        // 用户直接关闭弹窗：errMsg 含 cancel，视为未授权，静默返回
        if (err && err.errMsg && err.errMsg.includes('cancel')) {
          resolve(null);
          return;
        }
        resolve('error');
      },
    });
  });
}

/**
 * 登记一次授权结果；失败时用同一 request_id 重试一次。
 * B3 契约幂等：同 request_id、内容与事件一致时返回同一记录，不追加授权次数。
 * 返回 { status: 'ok' | 'already' }：409（重复登记）视为已订阅过，不当作错误。
 */
async function registerChoice(reminderId, templateId, choice, sessionToken) {
  const requestId = newRequestId();
  const payload = {
    reminder_id: reminderId,
    request_id: requestId,
    template_id: templateId,
    result: choice,
  };
  try {
    await api.wechatSubscribe(payload, sessionToken);
    return { status: 'ok', requestId };
  } catch (err) {
    if (String(err.message || '').includes('409')) {
      return { status: 'already', requestId };
    }
    // 网络抖动/后端瞬时故障：复用同一 request_id 重试一次，避免重复累计授权记录
    await api.wechatSubscribe(payload, sessionToken);
    return { status: 'ok', requestId };
  }
}

/**
 * 完整订阅流程（页面按钮触发）：授权 → 登录 → phone 提醒 → 登记。
 * 授权必须放在最前：微信要求 wx.requestSubscribeMessage 在用户点击的同步调用链中
 * 触发，先做网络请求会导致真机上弹窗被静默吞掉。
 * 返回 { status, message }：status 为 accept/reject/ban/filter/cancel/error。
 * 用户取消授权时不落库、不提示错误；拒绝不影响基础课表功能。
 */
async function subscribeTaskReminder(task) {
  const templateId = getTemplateId();
  if (!templateId) {
    throw new Error('未配置订阅模板 ID：请在 miniprogram/config.js 填写 subscribeTemplateId');
  }
  if (!task.remind_at) {
    throw new Error('该日程没有提醒时间，请先编辑设置');
  }
  // 本机提示：该任务已订阅过则不再重复弹授权框（业务状态以服务端为准）。
  // 服务通知页是用户可手动操作的开关：本地标记要跟随微信侧的当前设置，
  // 用户手动拒收后（总是保持状态仍在微信侧，代码无法清除），本地同步失效并给出指引。
  const flagKey = SUB_FLAG_PREFIX + task.id;
  if (wx.getStorageSync(flagKey) === 'done') {
    const remembered = await getRememberedSetting(templateId);
    if (remembered === 'reject' || remembered === 'ban') {
      wx.setStorageSync(flagKey, 'reject');
      return {
        status: 'setting-off',
        message: '检测到你在服务通知中已关闭接收消息。在微信「服务通知」重新开启接收后，再点订阅提醒即可',
      };
    }
    return { status: 'already', message: '该提醒已订阅过，无需重复授权' };
  }
  // 1) 同步触发授权弹窗（一次性订阅：无论同意与否，资格都随弹窗消耗）
  const choice = await requestSubscribe(templateId);
  if (choice === null) {
    // 真机上微信可能静默按旧选择返回（不再弹框）：查询记住的设置，给出恢复指引
    const remembered = await getRememberedSetting(templateId);
    if (remembered === 'reject' || remembered === 'ban') {
      return {
        status: 'remembered-reject',
        message: '微信已记住对该订阅的拒绝。可在微信「我-设置-个人信息与权限-授权管理」中恢复后重试',
      };
    }
    return { status: 'cancel', message: '' };
  }
  if (choice === 'error') {
    return { status: 'error', message: '授权弹窗调用失败，请重试' };
  }
  const classified = classifyResult(choice);
  // 2) 授权完成后再做网络请求；登录失败时本次授权已失效，提示用户恢复后重新订阅
  try {
    const session = await ensureSession();
    const reminderId = await ensurePhoneReminder(task, session);
    const registered = await registerChoice(reminderId, templateId, choice, session.session_token);
    if (registered.status === 'already') {
      wx.setStorageSync(flagKey, 'done');
      return { status: 'already', message: '该提醒已订阅过，无需重复授权' };
    }
    if (choice === 'accept') {
      wx.setStorageSync(flagKey, 'done');
    } else {
      wx.setStorageSync(flagKey, choice); // 拒绝后允许再次尝试
    }
  } catch (err) {
    if (choice === 'accept') {
      throw new Error(`${err.message || '网络请求失败'}；本次授权已失效，恢复后请重新订阅`);
    }
    throw err;
  }
  if (choice !== 'accept') {
    return {
      status: choice,
      message:
        classified.message +
        '。如曾勾选「总是保持以上选择」，可在微信「我-设置-个人信息与权限-授权管理」中恢复后重试',
    };
  }
  return { status: choice, message: classified.message };
}

module.exports = {
  getTemplateId,
  newRequestId,
  isSessionValid,
  classifyResult,
  subscribeTaskReminder,
};
