// 提醒开启流程（C3 简化版，2026-10-17 用户指示）：
// 点「开启提醒」为任务创建/更新 phone 提醒，到期时后端广播 reminder.due，
// 小程序内实时提醒（今日页提醒区 + 到期提示），无需微信授权弹窗。
// 微信离线推送仍由后端 B3 支持（docs/b3-wechat.md），本端不再走授权流程。

const api = require('./api');

/**
 * 开启/同步该任务的 phone 提醒（服务端为准，幂等）：
 * - 没有提醒 → 创建
 * - 已有且提醒时间变化 → 更新（B2 契约：修改生成新事件）
 * - 已有且未变化 → 不重复创建
 * 返回 { status: 'on', message }。
 */
async function subscribeTaskReminder(task) {
  if (!task.remind_at) {
    throw new Error('该日程没有提醒时间，请先编辑设置');
  }
  const reminders = await api.getReminders();
  const existing = reminders.find((r) => r.task_id === task.id && r.channel === 'phone');
  if (existing) {
    if (existing.remind_at !== task.remind_at) {
      await api.updateReminder(existing.id, {
        title: task.title,
        body: task.note || '',
        remind_at: task.remind_at,
      });
      return { status: 'on', message: '提醒时间已更新，到期将在小程序内提醒你' };
    }
    return { status: 'on', message: '该提醒已开启，到期将在小程序内提醒你' };
  }
  await api.createReminder({
    title: task.title,
    body: task.note || '',
    remind_at: task.remind_at,
    channel: 'phone',
    task_id: task.id,
  });
  return { status: 'on', message: '已开启提醒，到期将在小程序内提醒你' };
}

module.exports = { subscribeTaskReminder };
