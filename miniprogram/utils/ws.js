// WebSocket 事件适配层：集中管理与后端 /ws 的连接（契约见 docs/api-contract.md、
// docs/b8-accounts.md）。C9 起握手令牌为业务会话（Bearer 同一 session_token）：
// - 连接前先确保会话；重连时重新取当前会话令牌
// - 账号退出/切换后旧连接随会话代数失效，重建连接使用新令牌
// - 事件先按契约校验并以 event_id 去重，再分发给订阅者
// - 突发多条同类型事件做节流合并，避免页面请求风暴
// - 后端无历史事件补发：断线恢复后页面必须用 REST 重新读取（各页 onShow 已实现，
//   重连成功另发 'reconnect' 事件提醒页面刷新）

const { baseUrl } = require('./api');
const session = require('./session');

// ===== 集中配置 =====
// 重连退避序列（毫秒），用完后保持最后一个间隔
const RECONNECT_DELAYS = [1000, 2000, 4000, 8000, 16000, 30000];
// 同类型事件合并窗口（毫秒）：窗口内先发首条、窗口末补发最后一条
const EVENT_THROTTLE_MS = 400;
// event_id 去重记忆上限（条）
const EVENT_ID_HISTORY = 200;
// ====================

// 契约允许的事件类型（docs/api-contract.md、docs/b6-contract.md；未知类型忽略）
const KNOWN_TYPES = [
  'task.created',
  'course.created',
  'reminder.due',
  'reminder.created',
  'reminder.updated',
  'reminder.deleted',
  'semester.updated',
  'course.updated',
  'course.deleted',
  'task.updated',
  'task.deleted',
];

let socket = null; // wx.SocketTask
let reconnectAttempts = 0;
let reconnectTimer = null;
let manualClose = false; // 主动关闭（切后台）不触发重连
const listeners = new Map(); // type -> Set<handler>（Set 保证重复订阅不叠加）
const seenEventIds = new Set();
const throttleStates = new Map(); // type -> { pending: payload | null }

function wsUrl(token) {
  // http(s)://host:port -> ws(s)://host:port/ws?token=<会话令牌>
  return baseUrl.replace(/^http/, 'ws') + '/ws?token=' + encodeURIComponent(token);
}

function emit(type, payload) {
  const handlers = listeners.get(type);
  if (!handlers || handlers.size === 0) {
    return;
  }
  handlers.forEach((fn) => {
    try {
      fn(payload);
    } catch (err) {
      console.warn('[ws] 订阅回调异常:', err);
    }
  });
}

// 节流合并：首条立即分发，窗口内后续事件只保留最后一条，窗口末补发
function throttledEmit(type, event) {
  const state = throttleStates.get(type);
  if (state) {
    state.pending = event;
    return;
  }
  throttleStates.set(type, { pending: null });
  emit(type, event);
  setTimeout(() => {
    const done = throttleStates.get(type);
    throttleStates.delete(type);
    if (done && done.pending) {
      emit(type, done.pending);
    }
  }, EVENT_THROTTLE_MS);
}

// 校验事件信封：version 1、event_id 非空、type 已知、data.id 正整数
function isValidEvent(event) {
  return (
    event &&
    event.version === 1 &&
    typeof event.event_id === 'string' &&
    event.event_id !== '' &&
    KNOWN_TYPES.includes(event.type) &&
    event.data &&
    Number.isInteger(event.data.id) &&
    event.data.id > 0
  );
}

function handleMessage(res) {
  let event;
  try {
    event = JSON.parse(res.data);
  } catch (err) {
    return; // 非 JSON 帧忽略
  }
  if (!isValidEvent(event)) {
    console.warn('[ws] 忽略不符合契约的事件:', event);
    return;
  }
  if (seenEventIds.has(event.event_id)) {
    return; // 重复事件（如重连前已收到）
  }
  seenEventIds.add(event.event_id);
  if (seenEventIds.size > EVENT_ID_HISTORY) {
    seenEventIds.delete(seenEventIds.values().next().value);
  }
  throttledEmit(event.type, event);
}

async function connect() {
  if (socket || manualClose) {
    return;
  }
  // 显式退出登录：保持未登录，不自动重新登录/重连（等用户手动登录）
  if (session.isLoggedOut()) {
    return;
  }
  // 会话令牌随登录/重登变化：每次建立连接前确保有效会话
  let token;
  try {
    await session.ensureSession();
    token = session.token();
  } catch (err) {
    console.warn('[ws] 会话不可用，稍后重连:', err && err.message);
    scheduleReconnect();
    return;
  }
  if (!token || socket || manualClose) {
    return;
  }
  const attemptEpoch = session.epochNow();
  socket = wx.connectSocket({ url: wsUrl(token) });
  socket.onOpen(() => {
    if (reconnectAttempts > 0) {
      emit('reconnect', null); // 重连成功：提醒页面 REST 重读
    }
    reconnectAttempts = 0;
  });
  socket.onMessage(handleMessage);
  socket.onClose(() => {
    socket = null;
    // 会话期间退出/切换（epoch 变化）：按退避重连并使用新会话
    if (session.epochNow() !== attemptEpoch) {
      reconnectAttempts = 0;
    }
    scheduleReconnect();
  });
  socket.onError(() => {
    // 连接错误：随后的 onClose 统一走重连逻辑
    console.warn('[ws] 连接错误');
  });
}

function scheduleReconnect() {
  if (manualClose || reconnectTimer) {
    return;
  }
  const index = Math.min(reconnectAttempts, RECONNECT_DELAYS.length - 1);
  reconnectAttempts += 1;
  reconnectTimer = setTimeout(() => {
    reconnectTimer = null;
    connect();
  }, RECONNECT_DELAYS[index]);
}

/** 启动适配层：连接并挂载前后台生命周期（App.onLaunch 调用一次）。 */
function start() {
  connect();
  wx.onAppShow(() => {
    manualClose = false;
    connect(); // 回前台：断线则重连；页面 onShow 同时做 REST 重读
  });
  wx.onAppHide(() => {
    stop(); // 切后台：主动断开省资源
  });
  // 退出/切换账号：旧连接作废，按退避重建（使用新会话令牌）
  session.onEpochChange(() => {
    stop();
    manualClose = false;
    connect();
  });
}

/** 主动断开（切后台/显式停止），不触发重连。 */
function stop() {
  manualClose = true;
  if (reconnectTimer) {
    clearTimeout(reconnectTimer);
    reconnectTimer = null;
  }
  if (socket) {
    try {
      socket.close({});
    } catch (err) {
      /* 已断开时忽略 */
    }
    socket = null;
  }
  reconnectAttempts = 0;
}

/**
 * 订阅事件：type 为 KNOWN_TYPES 之一或 'reconnect'。
 * 同一 handler 重复订阅只生效一次（Set 去重）。
 */
function on(type, handler) {
  if (!listeners.has(type)) {
    listeners.set(type, new Set());
  }
  listeners.get(type).add(handler);
}

/** 取消订阅。 */
function off(type, handler) {
  const handlers = listeners.get(type);
  if (handlers) {
    handlers.delete(handler);
  }
}

module.exports = { start, stop, on, off };
