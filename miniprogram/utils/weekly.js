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

// 一次性提醒：未完成、非每周重复、也没有挂在日程下的提醒。
// 挂在日程下的提醒由对应日程行展示，这里跳过避免重复。
function oneOffReminders(reminders) {
  if (!Array.isArray(reminders)) {
    return [];
  }
  return reminders
    .filter((item) => item && !item.done && item.remind_at && !item.repeat_rule && !item.task_id)
    .map((item) => ({
      id: item.id,
      title: item.title || '',
      body: item.body || '',
      remind_at: item.remind_at,
    }))
    .sort((a, b) => String(a.remind_at).localeCompare(String(b.remind_at)));
}

module.exports = { WEEKDAY_LABELS, weeklyReminders, oneOffReminders, weekdayIndex };
