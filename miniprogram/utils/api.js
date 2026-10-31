// 后端接口统一封装：baseUrl 与 X-API-Key 集中配置于文件顶部。
// 契约（见 docs/api-contract.md 与 backend/app/routers/）：
// - 所有 REST 请求带 X-API-Key 请求头，由后端校验（backend/app/auth.py）
// - 课表 /api/courses、日程 /api/tasks 的 CRUD；字段以 backend/app/schemas.py 为准
// - 密钥不入库：真实 API Key 放 miniprogram/config.js（由 config.example.js 复制而来，已 gitignore）

let config = {};
try {
  config = require('../config');
} catch (err) {
  console.warn(
    '[api] 未找到 config.js，将使用默认地址且不带 API Key；' +
      '请复制 miniprogram/config.example.js 为 config.js 并填写真实值'
  );
}

// ===== 集中配置（顶部统一修改）=====
const baseUrl = config.baseUrl || 'http://127.0.0.1:8001';
const apiKey = config.apiKey || '';
// ==================================

/** 统一封装 wx.request：自动带 X-API-Key，返回 Promise，非 2xx 抛出带后端详情的错误。 */
function request(path, { method = 'GET', data, headers } = {}) {
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
function uploadWithTask(path, { filePath, name = 'image', formData } = {}) {
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

/** 旧版 upload 封装：兼容普通上传场景，返回 Promise（不暴露 task）。 */
function upload(path, { filePath, name = 'image', formData } = {}) {
  return uploadWithTask(path, { filePath, name, formData }).done;
}

module.exports = {
  baseUrl,
  apiKey,
  uploadWithTask,
  cancelledError,

  // 课表
  getCourses: () => request('/api/courses'),
  createCourse: (data) => request('/api/courses', { method: 'POST', data }),
  updateCourse: (id, data) => request(`/api/courses/${id}`, { method: 'PUT', data }),
  deleteCourse: (id) => request(`/api/courses/${id}`, { method: 'DELETE' }),

  // 课表图片识别导入（B7 契约见 docs/b7-parsing.md；可用 uploadWithTask 拿到任务句柄以取消）
  parseCourseImage: (filePath) => upload('/api/courses/parse-image', { filePath, name: 'image' }),
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

  // 学期与日历（B6 契约见 docs/b6-contract.md；未配置时 GET 返回 settings=null）
  getSemester: () => request('/api/semester'),
  saveSemester: (settings) => request('/api/semester', { method: 'PUT', data: settings }),
  getCalendar: (date) =>
    request('/api/calendar' + (date ? '?date=' + encodeURIComponent(date) : '')),

  // 微信登录与订阅登记（B3；订阅接口需 Bearer 会话头，见契约）
  wechatLogin: (code) => request('/api/wechat/login', { method: 'POST', data: { code } }),
  ensurePhoneReminder: (taskId, token) =>
    request('/api/wechat/reminders', {
      method: 'POST',
      data: { task_id: taskId },
      headers: { Authorization: `Bearer ${token}` },
    }),
  getWechatReminders: (token) =>
    request('/api/wechat/reminders', {
      headers: { Authorization: `Bearer ${token}` },
    }),
  getWechatReminder: (id, token) =>
    request(`/api/wechat/reminders/${id}`, {
      headers: { Authorization: `Bearer ${token}` },
    }),
  getSubscriptions: (id, token) =>
    request(`/api/wechat/subscriptions/${id}`, {
      headers: { Authorization: `Bearer ${token}` },
    }),
  wechatSubscribe: (data, sessionToken) =>
    request('/api/wechat/subscribe', {
      method: 'POST',
      data,
      headers: { Authorization: `Bearer ${sessionToken}` },
    }),
};
