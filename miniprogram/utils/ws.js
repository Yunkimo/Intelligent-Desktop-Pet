// WebSocket 事件适配层：集中管理与后端 /ws 的连接（契约见 docs/api-contract.md）。
// - 连接、重连退避、前后台生命周期统一在此管理，页面不得各自建连
// - 事件先按契约校验并以 event_id 去重，再分发给订阅者
// - 突发多条同类型事件做节流合并，避免页面请求风暴
// - 后端无历史事件补发：断线恢复后页面必须用 REST 重新读取（各页 onShow 已实现，
//   重连成功另发 'reconnect' 事件提醒页面刷新）

const { baseUrl, apiKey } = require('./api');

// ===== 集中配置 =====
// 重连退避序列（毫秒），用完后保持最后一个间隔
const RECONNECT_DELAYS = [1000, 2000, 4000, 8000, 16000, 30000];
// 同类型事件合并窗口（毫秒）：窗口内先发首条、窗口末补发最后一条
const EVENT_THROTTLE_MS = 400;
// event_id 去重记忆上限（条）
const EVENT_ID_HISTORY = 200;
// ====================

// 契约允许的事件类型（docs/api-contract.md；未知类型忽略）
const KNOWN_TYPES = ['task.created', 'course.created', 'reminder.due'];

let socket = null; // wx.SocketTask
let reconnectAttempts = 0;
let reconnectTimer = null;
let manualClose = false; // 主动关闭（切后台）不触发重连
const listeners = new Map(); // type -> Set<handler>（Set 保证重复订阅不叠加）
const seenEventIds = new Set();
const throttleStates = new Map(); // type -> { pending: payload | null }

function wsUrl() {
  // http(s)://host:port -> ws(s)://host:port/ws?token=<API_TOKEN>
  return baseUrl.replace(/^http/, 'ws') + '/ws?token=' + encodeURIComponent(apiKey);
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

function connect() {
  if (socket || manualClose || !apiKey) {
    return;
  }
  socket = wx.connectSocket({ url: wsUrl() });
  socket.onOpen(() => {
    if (reconnectAttempts > 0) {
      emit('reconnect', null); // 重连成功：提醒页面 REST 重读
    }
    reconnectAttempts = 0;
  });
  socket.onMessage(handleMessage);
  socket.onClose(() => {
    socket = null;
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
  if (!apiKey) {
    console.warn('[ws] 未配置 apiKey（miniprogram/config.js），跳过 WebSocket 连接');
    return;
  }
  connect();
  wx.onAppShow(() => {
    manualClose = false;
    connect(); // 回前台：断线则重连；页面 onShow 同时做 REST 重读
  });
  wx.onAppHide(() => {
    stop(); // 切后台：主动断开省资源
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
 * 订阅事件：type 为 'task.created' / 'course.created' / 'reminder.due' / 'reconnect'。
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
