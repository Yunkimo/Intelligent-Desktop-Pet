// 带伞提醒的纯逻辑与本地偏好（C 任务书「小程序带伞提示与微信订阅交互」，B 契约见
// docs 与 weather-subscriptions.md）：
// - 默认城市长沙，手动城市偏好按账号保存（暂无共享偏好接口，不与桌宠自动同步）
// - 订阅状态→文案与可操作判定（prepared 待授权 / pending 已登记 / sent 已发送等）
// - 城市规范化与「明天」标签；不编造雨量/时段，不把天气响应当发送凭据

const session = require('./session');

const DEFAULT_CITY = '长沙';
const CITY_KEY_PREFIX = 'weather_city:';
const CITY_MAX_LENGTH = 80;
const COMMON_CITIES = [
  '长沙',
  '北京',
  '上海',
  '广州',
  '深圳',
  '杭州',
  '成都',
  '武汉',
  '南京',
  '西安',
];

const STATUS_TEXT = {
  prepared: '待授权',
  pending: '已授权，今晚判断天气',
  checking: '正在检查天气',
  retry_weather: '天气暂不可用，稍后重查',
  sending: '微信发送中',
  retry: '发送重试中',
  sent: '已发送，请查看微信',
  no_rain: '本次无降水，不发送',
  rejected: '未取得授权',
  cancelled: '已取消',
  expired: '已过期',
  failed: '发送失败',
  uncertain: '发送结果待核实',
};

/** 城市偏好按账号隔离；未登录时用本地默认键。 */
function cityKey() {
  return CITY_KEY_PREFIX + (session.accountId() || 'local');
}

function getSavedCity() {
  const saved = wx.getStorageSync(cityKey());
  return typeof saved === 'string' && saved.trim() ? saved : DEFAULT_CITY;
}

function saveCity(city) {
  const normalized = normalizeCity(city);
  wx.setStorageSync(cityKey(), normalized);
  return normalized;
}

/** 规范化城市：去空白、限长；空返回 null。 */
function normalizeCity(text) {
  const value = String(text || '')
    .trim()
    .slice(0, CITY_MAX_LENGTH);
  return value || null;
}

/** 订阅状态→展示文案；未知状态原样返回（以后端契约为准）。 */
function statusText(status) {
  if (!status) {
    return '';
  }
  return STATUS_TEXT[status] || status;
}

/**
 * 是否允许（重新）订阅：未订阅、prepared（待授权）、rejected、cancelled 可再次主动授权；
 * 其余状态不引导重复授权（不盲目再弹授权框）。
 */
function canSubscribe(status) {
  return !status || status === 'prepared' || status === 'rejected' || status === 'cancelled';
}

/** 目标日期 → 「明天（11-05）」标签。 */
function tomorrowLabel(dateText) {
  if (!dateText) {
    return '明天';
  }
  const match = String(dateText).match(/^\d{4}-(\d{2})-(\d{2})$/);
  return match ? `明天（${match[1]}-${match[2]}）` : dateText;
}

/** 天气卡片文案：rain=true 带伞提示；rain=false 无降水；unknown 暂不可用。 */
function weatherCardText(weather) {
  if (!weather || weather.status === 'unknown') {
    return { headline: '天气暂不可用', sub: weather && weather.desc ? weather.desc : '' };
  }
  if (weather.rain === true) {
    return { headline: '明天可能有降水，记得带伞', sub: weather.desc || weather.tip || '' };
  }
  if (weather.rain === false) {
    return { headline: '明天暂无降水提示', sub: weather.desc || '' };
  }
  return { headline: '天气暂不可用', sub: (weather && weather.desc) || '' };
}

module.exports = {
  DEFAULT_CITY,
  COMMON_CITIES,
  getSavedCity,
  saveCity,
  normalizeCity,
  statusText,
  canSubscribe,
  tomorrowLabel,
  weatherCardText,
};
