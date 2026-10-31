// 学期状态适配层：集中管理 B6 学期配置与日历查询（契约见 docs/b6-contract.md）。
// - 在线优先取服务端结果（服务端按配置时区决定「今天」）；已确认的学期设置缓存到本地
// - 请求失败时用缓存的学期设置按本机日历日期推算周次，并标记 offline 提示用户
// - 旧「current_week」固定周缓存已废弃：不再读取，也不反推开学日期
// - 页面不得自行拼 semester/calendar 请求或缓存，统一走本模块

const api = require('./api');
const { computeWeek, todayDow, localDateText, parseDate } = require('./datetime');

const SETTINGS_KEY = 'semester_settings';

function getCachedSettings() {
  const saved = wx.getStorageSync(SETTINGS_KEY);
  if (!saved || !parseDate(saved.start_date) || !Number.isInteger(saved.total_weeks)) {
    return null;
  }
  return saved;
}

function cacheSettings(settings) {
  if (settings && parseDate(settings.start_date) && Number.isInteger(settings.total_weeks)) {
    wx.setStorageSync(SETTINGS_KEY, settings);
  }
}

function clearCachedSettings() {
  wx.removeStorageSync(SETTINGS_KEY);
}

/**
 * 读取服务端学期配置。
 * 返回 { ok, configured, settings }；请求失败返回 { ok: false }（不覆盖本地缓存）。
 */
async function getSettings() {
  try {
    const data = await api.getSemester();
    if (data && data.configured && data.settings) {
      cacheSettings(data.settings);
    } else if (data && data.configured === false) {
      clearCachedSettings();
    }
    return {
      ok: true,
      configured: !!(data && data.configured),
      settings: data ? data.settings : null,
    };
  } catch (err) {
    return { ok: false, configured: false, settings: null };
  }
}

/**
 * 整体保存学期设置（PUT，非部分更新）。成功后同步本地缓存。
 * 返回 { ok }；失败返回 { ok: false, error }。
 */
async function saveSettings(settings) {
  try {
    const data = await api.saveSemester(settings);
    if (data && data.settings) {
      cacheSettings(data.settings);
    }
    return { ok: true, settings: data ? data.settings : null };
  } catch (err) {
    return { ok: false, error: err.message || '保存失败' };
  }
}

/**
 * 查询服务端「今天」日历。请求失败时用缓存设置离线推算：
 * - 有缓存：返回 { ok, offline: true, week/status 由本地日历计算, courses: [] }
 * - 无缓存：返回 { ok: false }（无法确认学期，也区分不了未配置与服务不可达）
 */
async function getToday() {
  try {
    const data = await api.getCalendar();
    // 日历响应没有 configured 字段：settings=null 且 status=unconfigured 表示未配置
    if (data && data.status === 'unconfigured') {
      clearCachedSettings();
    } else if (data && data.settings) {
      cacheSettings(data.settings);
    }
    return Object.assign({ ok: true, offline: false }, data);
  } catch (err) {
    const cached = getCachedSettings();
    if (!cached) {
      return { ok: false, offline: true, error: err.message || '网络失败' };
    }
    const computed = computeWeek(cached.start_date, cached.total_weeks, localDateText());
    return {
      ok: true,
      offline: true,
      date: localDateText(),
      day_of_week: todayDow(),
      week: computed.week,
      status: computed.status,
      settings: cached,
      courses: [],
    };
  }
}

module.exports = { getSettings, saveSettings, getToday, getCachedSettings };
