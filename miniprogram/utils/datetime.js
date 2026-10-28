// 日期小工具：各页面共用的日期换算。

const WEEKDAY_LABELS = ['周一', '周二', '周三', '周四', '周五', '周六', '周日'];
let config = {};
try {
  config = require('../config');
} catch (_) {
  /* 使用契约默认时区 */
}
const OFFSET = config.reminderOffsetMinutes == null ? 480 : config.reminderOffsetMinutes;
const pad = (value) => String(value).padStart(2, '0');
function offsetText() {
  return (
    (OFFSET < 0 ? '-' : '+') +
    pad(Math.floor(Math.abs(OFFSET) / 60)) +
    ':' +
    pad(Math.abs(OFFSET) % 60)
  );
}
function reminderDate(value) {
  if (!value) {
    return new Date(NaN);
  }
  let text = value.replace(/(\.\d{3})\d+/, '$1');
  if (!/(Z|[+-]\d{2}:\d{2})$/i.test(text)) {
    text += offsetText();
  }
  return new Date(text);
}
function reminderParts(value) {
  const shifted = new Date(reminderDate(value).getTime() + OFFSET * 60000);
  if (!Number.isFinite(shifted.getTime())) {
    return { date: '', time: '' };
  }
  return {
    date:
      shifted.getUTCFullYear() +
      '-' +
      pad(shifted.getUTCMonth() + 1) +
      '-' +
      pad(shifted.getUTCDate()),
    time: pad(shifted.getUTCHours()) + ':' + pad(shifted.getUTCMinutes()),
  };
}
function reminderInput(date, time) {
  return date + 'T' + time + ':00' + offsetText();
}

/** Date → "YYYY-MM-DD"。 */
function dateStr(date) {
  const pad = (n) => String(n).padStart(2, '0');
  return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())}`;
}

/** 今天对应的后端 day_of_week（1=周一 … 7=周日；JS getDay() 0=周日）。 */
function todayDow() {
  const day = new Date().getDay();
  return day === 0 ? 7 : day;
}

// 本学期可选周次（1-25 周，覆盖常见学期长度）
const WEEK_OPTIONS = Array.from({ length: 25 }, (_, i) => `第${i + 1}周`);

const CURRENT_WEEK_KEY = 'current_week';

/** 读取用户设置的「本周周次」，未设置默认第 6 周。 */
function getCurrentWeek() {
  const saved = wx.getStorageSync(CURRENT_WEEK_KEY);
  const week = Number(saved);
  return saved && Number.isInteger(week) && week >= 1 && week <= 25 ? week : 6;
}

/** 保存「本周周次」。 */
function setCurrentWeek(week) {
  wx.setStorageSync(CURRENT_WEEK_KEY, Number(week));
}

/** 后端 weeks 字段可能是 JSON 字符串（如 "[1,2,3]"）或数组；解析为数字数组，空/无返回 []。 */
function parseWeeks(value) {
  let list = value;
  if (typeof value === 'string') {
    try {
      list = JSON.parse(value || '[]');
    } catch (err) {
      list = [];
    }
  }
  return Array.isArray(list) ? list : [];
}

/** 当前周是否在该课程的上课周次内（无周次 = 全周 = 每周都上）。 */
function isActiveWeek(course, week) {
  const weeks = parseWeeks(course.weeks);
  return weeks.length === 0 || weeks.includes(Number(week));
}

module.exports = {
  reminderDate,
  reminderParts,
  reminderInput,
  WEEKDAY_LABELS,
  WEEK_OPTIONS,
  dateStr,
  todayDow,
  getCurrentWeek,
  setCurrentWeek,
  parseWeeks,
  isActiveWeek,
};
