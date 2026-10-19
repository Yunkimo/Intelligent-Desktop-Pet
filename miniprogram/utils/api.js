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

/** wx.uploadFile 封装：multipart 上传（课表图片识别），自动带 X-API-Key，返回 Promise。 */
function upload(path, { filePath, name = 'image', formData } = {}) {
  return new Promise((resolve, reject) => {
    wx.uploadFile({
      url: baseUrl + path,
      filePath,
      name,
      formData,
      timeout: 180000,
      header: {
        'X-API-Key': apiKey,
      },
      success(res) {
        if (res.statusCode >= 200 && res.statusCode < 300) {
          try {
            resolve(JSON.parse(res.data));
          } catch (err) {
            reject(new Error('响应解析失败'));
          }
          return;
        }
        let detail = '';
        try {
          const data = JSON.parse(res.data || '{}');
          detail = typeof data.detail === 'string' ? data.detail : '';
        } catch (err) {
          /* 非 JSON 响应，保持通用错误提示 */
        }
        reject(new Error(`HTTP ${res.statusCode}${detail ? `：${detail}` : ''}`));
      },
      fail(err) {
        reject(new Error(`上传失败：${err.errMsg || '请检查网络与后端服务'}`));
      },
    });
  });
}

module.exports = {
  baseUrl,
  apiKey,

  // 课表
  getCourses: () => request('/api/courses'),
  createCourse: (data) => request('/api/courses', { method: 'POST', data }),
  updateCourse: (id, data) => request(`/api/courses/${id}`, { method: 'PUT', data }),
  deleteCourse: (id) => request(`/api/courses/${id}`, { method: 'DELETE' }),

  // 课表图片识别导入
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
