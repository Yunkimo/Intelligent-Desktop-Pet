// 每周固定安排：从提醒列表挑出 repeat_rule=weekly 且未完成的，按周几+时间排序。
// 只做展示用，不改后端数据；到点提醒仍由后端调度。

const { reminderParts } = require('./datetime');

// getDay() 里 0 是周日，这里转成「周一在前」的顺序
const WEEKDAY_LABELS = ['周一', '周二', '周三', '周四', '周五', '周六', '周日'];

function weekdayIndex(dateText) {
  if (!dateText) {
    return 6;
  }
  const day = new Date(dateText + 'T00:00:00Z').getUTCDay();
  return Number.isFinite(day) ? (day + 6) % 7 : 6;
}

function weeklyReminders(reminders) {
  if (!Array.isArray(reminders)) {
    return [];
  }
  return reminders
    .filter((item) => item && !item.done && item.repeat_rule === 'weekly' && item.remind_at)
    .map((item) => {
      const parts = reminderParts(item.remind_at);
      const index = weekdayIndex(parts.date);
      return {
        id: item.id,
        title: item.title || '',
        body: item.body || '',
        weekday: WEEKDAY_LABELS[index],
        time: parts.time,
        sortKey: index * 10000 + Number(parts.time.replace(':', '')) || 0,
      };
    })
    .sort((a, b) => a.sortKey - b.sortKey);
}

module.exports = { WEEKDAY_LABELS, weeklyReminders, weekdayIndex };
