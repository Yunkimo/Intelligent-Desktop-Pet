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

// ===== 学期周次推算（B6 契约，纯日历计算，不依赖服务端）=====

/** 解析 "YYYY-MM-DD" 为 {y, m, d}；格式错误或日期不存在（如 02-30）返回 null。 */
function parseDate(text) {
  if (typeof text !== 'string') {
    return null;
  }
  const match = text.match(/^(\d{4})-(\d{2})-(\d{2})$/);
  if (!match) {
    return null;
  }
  const y = Number(match[1]);
  const m = Number(match[2]);
  const d = Number(match[3]);
  const date = new Date(Date.UTC(y, m - 1, d));
  if (date.getUTCFullYear() !== y || date.getUTCMonth() !== m - 1 || date.getUTCDate() !== d) {
    return null;
  }
  return { y, m, d };
}

/** 纯日历日差（a - b，天数）：用日期分量换算，不用毫秒差，夏令时地区也正确。非法日期返回 NaN。 */
function daysBetween(aText, bText) {
  const a = parseDate(aText);
  const b = parseDate(bText);
  if (!a || !b) {
    return NaN;
  }
  const toDays = (p) => Date.UTC(p.y, p.m - 1, p.d) / 86400000;
  return toDays(a) - toDays(b);
}

/**
 * 按学期设置推算某日期的周次与状态（与后端同算法：日历日差整除 7 加 1）。
 * 返回 { week, status }：status ∈ before_term / in_term / after_term / unconfigured；
 * 只有 in_term 有真实 week，学期外 week=null（不夹到第 1/最后一周）。
 */
function computeWeek(startDate, totalWeeks, dateText) {
  if (
    !parseDate(startDate) ||
    !Number.isInteger(totalWeeks) ||
    totalWeeks < 1 ||
    totalWeeks > 53 ||
    !parseDate(dateText)
  ) {
    return { week: null, status: 'unconfigured' };
  }
  const diff = daysBetween(dateText, startDate);
  if (diff < 0) {
    return { week: null, status: 'before_term' };
  }
  if (diff >= totalWeeks * 7) {
    return { week: null, status: 'after_term' };
  }
  return { week: Math.floor(diff / 7) + 1, status: 'in_term' };
}

/** 该日期是否为周一（用于学期设置校验：第一周起始日期必须为周一）。 */
function isMonday(text) {
  const p = parseDate(text);
  return p !== null && new Date(Date.UTC(p.y, p.m - 1, p.d)).getUTCDay() === 1;
}

/** 本机当地日历今天（YYYY-MM-DD）；离线推算周次时作为「今天」。 */
function localDateText() {
  return dateStr(new Date());
}

/** 总周数（1-53）对应的周次选项，供「浏览其他周」选择器使用。 */
function weekNumberOptions(totalWeeks) {
  const count = Number.isInteger(totalWeeks) ? Math.min(Math.max(totalWeeks, 1), 53) : 25;
  return Array.from({ length: count }, (_, i) => `第${i + 1}周`);
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
  dateStr,
  todayDow,
  parseWeeks,
  isActiveWeek,
  parseDate,
  daysBetween,
  computeWeek,
  isMonday,
  localDateText,
  weekNumberOptions,
};
