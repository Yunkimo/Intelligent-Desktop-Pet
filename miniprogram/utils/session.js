// 统一会话管理（C9，B8 契约见 docs/b8-accounts.md）：
// - 微信登录 POST /api/wechat/login 换取业务会话（session_token/account_id/expires_in）
// - 业务请求/上传/WS 统一用 Authorization: Bearer <session_token>；API Key 不再用于业务
// - 登录并发合并为一次请求；401 恢复由各调用方按「单次重登」处理
// - 退出/切换账号：撤销会话、清理账号相关缓存，并推进会话代数（epoch），
//   旧账号的迟到响应凭代数丢弃，不污染新账号状态
// 本模块不依赖 api.js（由 api.js 启动时注入登录实现），避免循环依赖。

const SESSION_SKEW_SECONDS = 60;
const ACCOUNT_PREFIX = 'account:';
const LOGGED_OUT_KEY_PREFIX = 'logged_out:';

let baseUrl = '';
let loginImpl = null; // { wechatLogin(code), authLogout(token) }
let loginFlight = null;
let epoch = 0;
const epochListeners = new Set();

/** 会话存储键按后端地址隔离（与 C3 订阅模块历史行为一致）。 */
function sessionKey() {
  return 'wechat_session:' + baseUrl;
}

/** api.js 启动时注入登录实现与后端地址；重复注入取最后一次。 */
function setApi(impl) {
  loginImpl = impl;
  baseUrl = impl.baseUrl || '';
}

function requireLoginImpl() {
  if (!loginImpl) {
    throw new Error('会话模块未初始化（缺少登录实现）');
  }
}

function loggedOutKey() {
  return LOGGED_OUT_KEY_PREFIX + baseUrl;
}

/** 用户是否显式退出登录（退出后保持未登录，直到手动登录）。 */
function isLoggedOut() {
  return !!wx.getStorageSync(loggedOutKey());
}

function loggedOutError() {
  const error = new Error('尚未登录，请到「设置」页登录');
  error.loggedOut = true;
  return error;
}

function cachedSession() {
  return wx.getStorageSync(sessionKey()) || null;
}

function isSessionValid(session, now) {
  return (
    !!session &&
    typeof session.session_token === 'string' &&
    session.session_token !== '' &&
    !!session.expires_at &&
    now < session.expires_at - SESSION_SKEW_SECONDS * 1000
  );
}

/** 当前会话令牌；未登录返回 null（调用方决定是否走登录）。 */
function token() {
  const session = cachedSession();
  return session ? session.session_token : null;
}

/** 当前业务账号 ID（account_id 优先，兼容旧字段 user_id）；未登录返回 null。 */
function accountId() {
  const session = cachedSession();
  if (!session) {
    return null;
  }
  return session.account_id || session.user_id || null;
}

/** 会话代数：账号切换后旧请求据此丢弃迟到响应。 */
function epochNow() {
  return epoch;
}

/** 注册会话代数变化回调（退出/重登时用于清理 WS 与缓存）。 */
function onEpochChange(handler) {
  epochListeners.add(handler);
}

/**
 * 确保有效会话：缓存有效直接返回；否则 wx.login 换取新会话（并发合并为一次）。
 * 返回会话对象；失败抛出带中文提示的错误。
 */
async function ensureSession() {
  if (isLoggedOut()) {
    throw loggedOutError();
  }
  const cached = cachedSession();
  if (isSessionValid(cached, Date.now())) {
    return cached;
  }
  if (!loginFlight) {
    loginFlight = (async () => {
      requireLoginImpl();
      const result = await new Promise((resolve, reject) =>
        wx.login({
          success: resolve,
          fail: () => reject(new Error('微信登录失败，请检查网络后重试')),
        })
      );
      if (!result.code) {
        throw new Error('微信未返回登录 code');
      }
      const response = await loginImpl.wechatLogin(result.code);
      const session = { ...response, expires_at: Date.now() + response.expires_in * 1000 };
      wx.setStorageSync(sessionKey(), session);
      return session;
    })().finally(() => {
      loginFlight = null;
    });
  }
  return loginFlight;
}

/** 清除本地会话并推进代数（旧账号迟到响应全部作废）。 */
function clearSession() {
  wx.removeStorageSync(sessionKey());
  epoch += 1;
  epochListeners.forEach((fn) => {
    try {
      fn();
    } catch (err) {
      /* 监听器异常不影响主流程 */
    }
  });
}

/** 按当前账号清理业务缓存（学期配置等；键以账号前缀隔离，旧账号缓存自然失活）。 */
function clearAccountCache() {
  const account = accountId();
  if (account) {
    wx.removeStorageSync(ACCOUNT_PREFIX + account);
    wx.removeStorageSync('semester_settings:' + account);
    return;
  }
  let keys = [];
  try {
    keys = (wx.getStorageInfoSync().keys || []).filter((key) =>
      key.startsWith('semester_settings')
    );
  } catch (err) {
    keys = [];
  }
  keys.forEach((key) => wx.removeStorageSync(key));
}

/**
 * 退出登录：尽力撤销服务端会话（失败不阻塞），清理本地会话与账号缓存。
 * 返回 { ok, revoked }；revoked=false 表示服务端撤销请求未成功（本地仍已登出）。
 */
async function logout() {
  const current = cachedSession();
  let revoked = false;
  if (current && current.session_token && loginImpl && loginImpl.authLogout) {
    try {
      await loginImpl.authLogout(current.session_token);
      revoked = true;
    } catch (err) {
      revoked = false;
    }
  }
  clearAccountCache();
  wx.setStorageSync(loggedOutKey(), true); // 先标记退出，再清会话：自动重连不会重新登录
  clearSession();
  return { ok: true, revoked };
}

/** 手动登录：清除退出标记并换取新会话；返回会话对象。 */
async function login() {
  wx.removeStorageSync(loggedOutKey());
  const result = await ensureSession();
  epoch += 1; // 通知 WS 等使用新会话
  epochListeners.forEach((fn) => {
    try {
      fn();
    } catch (err) {
      /* 监听器异常不影响主流程 */
    }
  });
  return result;
}

/** 强制当前会话过期（下次请求触发重新登录）；保留其余字段供恢复逻辑使用。 */
function forceExpire() {
  const cached = cachedSession();
  if (cached) {
    wx.setStorageSync(sessionKey(), { ...cached, expires_at: 0 });
  }
}

module.exports = {
  setApi,
  ensureSession,
  login,
  isLoggedOut,
  logout,
  clearSession,
  forceExpire,
  clearAccountCache,
  token,
  accountId,
  epochNow,
  onEpochChange,
  isSessionValid,
  sessionKey,
};
