// 消息落地页：参数只是资源标识，读取数据必须通过当前用户会话校验。
const api = require('../../utils/api');
const { withSession, resultFor } = require('../../utils/subscribe');
const { reminderParts } = require('../../utils/datetime');
Page({
  data: { loading: false, error: '', task: null, reminder: null, time: '', status: '' },
  onLoad(options) {
    this.reminderId = /^\d+$/.test(options.reminder_id || '') ? Number(options.reminder_id) : null;
  },
  onShow() {
    return this.load();
  },
  async load() {
    if (!Number.isSafeInteger(this.reminderId) || this.reminderId <= 0) {
      this.setData({ error: '消息中的提醒标识无效' });
      return;
    }
    this.setData({ loading: true, error: '', task: null, reminder: null, status: '' });
    try {
      const result = await withSession(async (session) => {
        const detail = await api.getWechatReminder(this.reminderId, session.session_token);
        const records = await api.getSubscriptions(this.reminderId, session.session_token);
        return { ...detail, records };
      });
      const current = result.records.find((r) => r.event_id === result.reminder.event_id);
      const time = reminderParts(result.reminder.remind_at);
      this.setData({
        task: result.task,
        reminder: result.reminder,
        time: time.date + ' ' + time.time,
        status: current ? resultFor(current).message : '当前提醒尚未登记订阅',
      });
    } catch (error) {
      this.setData({
        error:
          error.statusCode === 404
            ? '提醒已删除或当前账号无法访问'
            : error.message || '加载失败，请重试',
      });
    } finally {
      this.setData({ loading: false });
    }
  },
  retry() {
    return this.load();
  },
  openTasks() {
    wx.switchTab({ url: '/pages/task/task' });
  },
});
