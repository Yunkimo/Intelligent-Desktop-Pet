// 后端接口统一封装：baseUrl 集中配置于文件顶部（C9 起业务统一走 B8 会话）。
// 契约（见 docs/api-contract.md、docs/b8-accounts.md 与 backend/app/routers/）：
// - 业务请求统一 Authorization: Bearer <session_token>（utils/session.js 管理登录与重登）
// - 401 单次重登后重试一次；仍 401 抛 authRequired；写请求不明结果不盲目重放
// - API Key 仅保留兼容旧后端（B8 过渡期映射默认演示用户），不用于小程序业务请求
// - 账号退出/切换后旧账号迟到响应按会话代数丢弃
// - 密钥不入库：真实配置放 miniprogram/config.js（由 config.example.js 复制而来，已 gitignore）

let config = {};
try {
  config = require('../config');
} catch (err) {
  console.warn(
    '[api] 未找到 config.js，将使用默认地址且不带 API Key；' +
      '请复制 miniprogram/config.example.js 为 config.js 并填写真实值'
  );
}

const session = require('./session');

// ===== 集中配置（顶部统一修改）=====
const baseUrl = config.baseUrl || 'http://127.0.0.1:8001';
const apiKey = config.apiKey || '';
// ==================================

/** 无会话处理的底层请求：自动带 X-API-Key（兼容旧后端），返回 Promise。 */
function rawRequest(path, { method = 'GET', data, headers } = {}) {
  return new Promise((resolve, reject) => {
    wx.request({
      url: baseUrl + path,
      method,
      data,
      timeout: config.requestTimeoutMs || 15000,
      header: {
        'X-API-Key': apiKey,
        'Content-Type': 'application/json',
        ...(headers || {}),
      },
      success(res) {
        if (res.statusCode >= 200 && res.statusCode < 300) {
          resolve(res.data);
          return;
        }
        const detail =
          res.data && typeof res.data.detail === 'string'
            ? res.data.detail
            : typeof res.data === 'string'
              ? res.data
              : '';
        const error = new Error(`HTTP ${res.statusCode}${detail ? `：${detail}` : ''}`);
        error.statusCode = res.statusCode;
        error.code = detail;
        reject(error);
      },
      fail(err) {
        reject(new Error(`网络请求失败：${err.errMsg || '请检查后端是否启动、baseUrl 是否正确'}`));
      },
    });
  });
}

/** 账号已变化错误：调用方应丢弃本次操作并刷新页面数据。 */
function accountChangedError() {
  const error = new Error('登录账号已变化，请刷新后重试');
  error.accountChanged = true;
  return error;
}

/** 登录失效且重登失败：调用方给出「重新登录」入口。 */
function authRequiredError() {
  const error = new Error('登录失效，请重新登录');
  error.authRequired = true;
  return error;
}

/**
 * 业务请求：自动携带会话 Bearer；401 时清除会话、单次重登后重试一次；
 * 仍 401 抛 authRequired；重登前后账号不一致或会话被外部切换则抛 accountChanged，
 * 不把旧账号操作落到新账号上。auth=false 用于引导入口（微信登录等）。
 */
async function request(path, { method = 'GET', data, headers, auth = true } = {}) {
  if (!auth) {
    return rawRequest(path, { method, data, headers });
  }
  let current = await session.ensureSession();
  const startAccount = session.accountId();
  for (let attempt = 0; attempt < 2; attempt += 1) {
    const attemptEpoch = session.epochNow();
    let result;
    try {
      result = await rawRequest(path, {
        method,
        data,
        headers: { Authorization: 'Bearer ' + current.session_token, ...(headers || {}) },
      });
    } catch (err) {
      if (err.statusCode === 401 && attempt === 0) {
        // 单次重登恢复：清除失效会话后重新登录
        session.clearSession();
        current = await session.ensureSession();
        if (session.accountId() !== startAccount) {
          throw accountChangedError();
        }
        continue;
      }
      if (err.statusCode === 401) {
        throw authRequiredError();
      }
      throw err;
    }
    if (session.epochNow() !== attemptEpoch) {
      // 请求期间账号被退出/切换：丢弃旧账号迟到响应
      throw accountChangedError();
    }
    return result;
  }
}

/** 上传中止标记错误：页面据此区分「用户取消」与网络/服务错误。 */
function cancelledError() {
  const error = new Error('已取消');
  error.cancelled = true;
  return error;
}

/**
 * wx.uploadFile 封装：multipart 上传（课表图片识别），自动带 X-API-Key。
 * 返回 { task, done }：task 为 wx.UploadTask（可 abort），done 为 Promise；
 * abort 后 done 以 cancelled 标记拒绝，迟到的成功/失败回调不会再次结算。
 * 超时毫秒数默认取 config.parseTimeoutMs（B7 契约：客户端最多等 70 秒）。
 */
function uploadWithTask(path, { filePath, name = 'image', formData, headers } = {}) {
  let settled = false;
  let task = null;
  let rejectFn = null;
  const done = new Promise((resolve, reject) => {
    rejectFn = reject;
    const finish = (fn, value) => {
      if (settled) {
        return; // 忽略迟到响应（已超时/已取消/已成功）
      }
      settled = true;
      fn(value);
    };
    task = wx.uploadFile({
      url: baseUrl + path,
      filePath,
      name,
      formData,
      timeout: config.parseTimeoutMs || 70000,
      header: {
        'X-API-Key': apiKey,
        ...(headers || {}),
      },
      success(res) {
        if (res.statusCode >= 200 && res.statusCode < 300) {
          let data;
          try {
            data = JSON.parse(res.data);
          } catch (err) {
            finish(reject, new Error('响应解析失败'));
            return;
          }
          finish(resolve, data);
          return;
        }
        let detail = '';
        let code = '';
        try {
          const parsed = JSON.parse(res.data || '{}');
          if (typeof parsed.detail === 'string') {
            detail = parsed.detail;
          } else if (parsed.detail && typeof parsed.detail.message === 'string') {
            detail = parsed.detail.message;
            code = parsed.detail.code || '';
          }
        } catch (err) {
          /* 非 JSON 响应，保持通用错误提示 */
        }
        const error = new Error(`HTTP ${res.statusCode}${detail ? `：${detail}` : ''}`);
        error.statusCode = res.statusCode;
        error.code = code;
        finish(reject, error);
      },
      fail(err) {
        if (err && /abort|cancel/i.test(err.errMsg || '')) {
          finish(reject, cancelledError());
          return;
        }
        const message = (err && err.errMsg) || '';
        const error = new Error(
          /timeout/i.test(message)
            ? '识别超时（已等待 70 秒），请重试'
            : `上传失败：${message || '请检查网络与后端服务'}`
        );
        error.timeout = /timeout/i.test(message);
        finish(reject, error);
      },
    });
  });
  return {
    get task() {
      return task;
    },
    done,
    abort() {
      // 主动取消：中止底层任务并让 done 以 cancelled 标记拒绝；迟到回调被 finish 忽略
      if (!settled) {
        settled = true;
        if (task) {
          try {
            task.abort();
          } catch (err) {
            /* 任务已结束时忽略 */
          }
        }
        rejectFn(cancelledError());
      }
    },
  };
}

/**
 * 业务上传：与 request 相同的会话语义（Bearer、401 单次重登、账号切换丢弃）。
 * 返回 { done, abort }；abort 立即以 cancelled 结束等待。
 */
function authedUpload(path, { filePath, name = 'image', formData } = {}) {
  let inner = null;
  let cancelled = false;
  const handle = {
    done: null,
    abort() {
      cancelled = true;
      if (inner) {
        inner.abort();
      }
    },
  };
  handle.done = (async () => {
    let current = await session.ensureSession();
    const startAccount = session.accountId();
    for (let attempt = 0; attempt < 2; attempt += 1) {
      if (cancelled) {
        throw cancelledError();
      }
      const attemptEpoch = session.epochNow();
      inner = uploadWithTask(path, {
        filePath,
        name,
        formData,
        headers: { Authorization: 'Bearer ' + current.session_token },
      });
      let result;
      try {
        result = await inner.done;
      } catch (err) {
        if (err.statusCode === 401 && attempt === 0) {
          session.clearSession();
          current = await session.ensureSession();
          if (session.accountId() !== startAccount) {
            throw accountChangedError();
          }
          continue;
        }
        if (err.statusCode === 401) {
          throw authRequiredError();
        }
        throw err;
      }
      if (session.epochNow() !== attemptEpoch) {
        throw accountChangedError();
      }
      return result;
    }
  })();
  return handle;
}

// 会话模块的登录实现（引导入口不使用会话，避免循环依赖）
session.setApi({
  baseUrl,
  wechatLogin: (code) => rawRequest('/api/wechat/login', { method: 'POST', data: { code } }),
  authLogout: (token) =>
    rawRequest('/api/auth/logout', {
      method: 'POST',
      headers: { Authorization: 'Bearer ' + token },
    }),
});

module.exports = {
  baseUrl,
  apiKey,
  request,
  uploadWithTask,
  authedUpload,
  cancelledError,
  accountChangedError,
  authRequiredError,

  // 课表
  getCourses: () => request('/api/courses'),
  createCourse: (data) => request('/api/courses', { method: 'POST', data }),
  updateCourse: (id, data) => request(`/api/courses/${id}`, { method: 'PUT', data }),
  deleteCourse: (id) => request(`/api/courses/${id}`, { method: 'DELETE' }),

  // 课表图片识别导入（B7 契约见 docs/b7-parsing.md；authedUpload 返回 {done, abort} 可取消）
  parseCourseImage: (filePath) =>
    authedUpload('/api/courses/parse-image', { filePath, name: 'image' }),
  bulkCreateCourses: (courses) =>
    request('/api/courses/bulk', { method: 'POST', data: { courses } }),

  // 日程/待办
  getTasks: () => request('/api/tasks'),
  createTask: (data) => request('/api/tasks', { method: 'POST', data }),
  updateTask: (id, data) => request(`/api/tasks/${id}`, { method: 'PUT', data }),
  deleteTask: (id) => request(`/api/tasks/${id}`, { method: 'DELETE' }),

  // 提醒（B2/B3 契约见 docs/api-contract.md 与 backend/app/routers/reminders.py）
  getReminders: () => request('/api/reminders'),
  createReminder: (data) => request('/api/reminders', { method: 'POST', data }),
  updateReminder: (id, data) => request(`/api/reminders/${id}`, { method: 'PUT', data }),
  deleteReminder: (id) => request(`/api/reminders/${id}`, { method: 'DELETE' }),

  // 一句话日程解析（C8，B7 契约见 docs/b7-parsing.md 第二节）：只返回待确认草稿
  captureText: (data) => request('/api/capture', { method: 'POST', data }),
  confirmCapture: (id, option, stage = 'item') =>
    request('/api/capture/' + encodeURIComponent(id) + '/confirm', {
      method: 'POST', data: { option, stage },
    }),
  parseTaskText: (payload) => request('/api/tasks/parse-text', { method: 'POST', data: payload }),

  // 学期与日历（B6 契约见 docs/b6-contract.md；B8 起按账号隔离）
  getSemester: () => request('/api/semester'),
  saveSemester: (settings) => request('/api/semester', { method: 'PUT', data: settings }),
  getCalendar: (date) =>
    request('/api/calendar' + (date ? '?date=' + encodeURIComponent(date) : '')),

  // 账号（B8 契约见 docs/b8-accounts.md）：me 查当前业务账号，logout 撤销当前会话，
  // 生成一次性桌宠配对码，expires_in 为服务端有效期（秒）。
  authMe: () => request('/api/auth/me'),
  authPairing: () => request('/api/auth/pairing', { method: 'POST' }),

  // 带伞提醒（B 契约见 weather-subscriptions.md；订阅接口仅微信会话，普通卡片为业务会话）
  getWeatherTomorrow: (city) => request('/api/weather/tomorrow?city=' + encodeURIComponent(city)),
  weatherPrepare: (city) => request('/api/weather/subscriptions', { method: 'POST', data: { city } }),
  weatherAuthorize: (eventId, payload) =>
    request(`/api/weather/subscriptions/${eventId}/authorization`, { method: 'POST', data: payload }),
  getWeatherSubscriptions: () => request('/api/weather/subscriptions'),
  getWeatherSubscription: (id) => request(`/api/weather/subscriptions/${id}`),
  cancelWeatherSubscription: (id) =>
    request(`/api/weather/subscriptions/${id}`, { method: 'DELETE' }),
  authLogout: (token) =>
    rawRequest('/api/auth/logout', {
      method: 'POST',
      headers: { Authorization: 'Bearer ' + token },
    }),

  // 微信登录与订阅登记（B3；登录为引导入口不要求会话，订阅接口需 Bearer 会话头）
  wechatLogin: (code) =>
    request('/api/wechat/login', { method: 'POST', data: { code }, auth: false }),
  ensurePhoneReminder: (taskId, token) =>
    request('/api/wechat/reminders', {
      method: 'POST',
      data: { task_id: taskId },
      headers: { Authorization: `Bearer ${token}` },
      auth: false,
    }),
  getWechatReminders: (token) =>
    request('/api/wechat/reminders', {
      headers: { Authorization: `Bearer ${token}` },
      auth: false,
    }),
  getWechatReminder: (id, token) =>
    request(`/api/wechat/reminders/${id}`, {
      headers: { Authorization: `Bearer ${token}` },
      auth: false,
    }),
  getSubscriptions: (id, token) =>
    request(`/api/wechat/subscriptions/${id}`, {
      headers: { Authorization: `Bearer ${token}` },
      auth: false,
    }),
  wechatSubscribe: (data, sessionToken) =>
    request('/api/wechat/subscribe', {
      method: 'POST',
      data,
      headers: { Authorization: `Bearer ${sessionToken}` },
      auth: false,
    }),
};
