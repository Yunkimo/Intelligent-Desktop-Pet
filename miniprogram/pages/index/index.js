// 今日页：展示服务端「今天」的真实周次与当天课表、到期/逾期待办与今日提醒。
// 周次来自 B6 日历接口（按学期设置与配置时区计算），不再是本地固定的 current_week；
// 未设置学期时引导去设置，学期外/离线分别给出可理解的状态。
const api = require('../../utils/api');
const ws = require('../../utils/ws');
const semester = require('../../utils/semester');
const { WEEKDAY_LABELS, reminderParts } = require('../../utils/datetime');

// 今日页关心的后端事件（WebSocket 推送后 REST 重读，节流由 ws.js 统一处理）
const WS_EVENTS = [
  'task.created',
  'task.updated',
  'task.deleted',
  'course.created',
  'course.updated',
  'course.deleted',
  'semester.updated',
  'reminder.due',
  'reconnect',
];

const STATUS_TEXT = {
  unconfigured: '未设置学期',
  before_term: '学期未开始',
  after_term: '学期已结束',
};

Page({
  data: {
    todayLabel: '',
    statusText: '',
    needSetup: false,
    offline: false,
    courses: [],
    tasks: [],
    reminders: [],
    loading: false,
    error: '',
  },

  onShow() {
    WS_EVENTS.forEach((type) => ws.on(type, this.onWsEvent));
    this.scheduleMidnightReload();
    this.loadToday();
  },

  onHide() {
    WS_EVENTS.forEach((type) => ws.off(type, this.onWsEvent));
  },

  onUnload() {
    WS_EVENTS.forEach((type) => ws.off(type, this.onWsEvent));
    if (this._midnightTimer) {
      clearTimeout(this._midnightTimer);
      this._midnightTimer = null;
    }
  },

  // 后端事件到达：REST 重读（onShow 也走这里，覆盖断线恢复与跨端修改）
  onWsEvent(event) {
    if (event && event.type === 'reminder.due') {
      wx.showToast({ title: '有提醒到期', icon: 'none', duration: 3000 });
    }
    this.loadToday();
  },

  onPullDownRefresh() {
    this.loadToday().finally(() => wx.stopPullDownRefresh());
  },

  // 跨午夜校准：页面停留时到本地次日 00:00:05 自动重新读取「今天」
  scheduleMidnightReload() {
    if (this._midnightTimer) {
      clearTimeout(this._midnightTimer);
    }
    const now = new Date();
    const next = new Date(now.getFullYear(), now.getMonth(), now.getDate() + 1, 0, 0, 5);
    this._midnightTimer = setTimeout(() => this.loadToday(), next.getTime() - now.getTime());
  },

  openSemester() {
    wx.navigateTo({ url: '/pages/semester/semester' });
  },

  async loadToday() {
    this.setData({ loading: true, error: '' });
    const errors = [];
    // 学期/日历：失败不阻塞待办与提醒（二者不依赖学期）
    try {
      const today = await semester.getToday();
      if (!today.ok) {
        // 服务器不可达且本地没有已确认的学期配置：无法确认周次
        errors.push('无法确认周次：服务器不可达且本机没有学期配置');
        this.setData({ todayLabel: '', needSetup: false, offline: true, courses: [] });
      } else {
        const status = today.status;
        const weekLabel =
          status === 'in_term'
            ? `第${today.week}周 · ${WEEKDAY_LABELS[today.day_of_week - 1]} · ${today.date}`
            : STATUS_TEXT[status] || today.date;
        this.setData({
          todayLabel: weekLabel + (today.offline ? '（离线推算）' : ''),
          statusText: status === 'in_term' ? '' : STATUS_TEXT[status] || '',
          needSetup: status === 'unconfigured',
          offline: !!today.offline,
          courses: (today.courses || []).map((c) => ({ ...c })),
        });
      }
    } catch (err) {
      errors.push(err.message || '加载失败');
    }
    // 待办与提醒不依赖学期：无论学期状态如何都照常加载
    const [tasksRes, remindersRes] = await Promise.allSettled([api.getTasks(), api.getReminders()]);
    const tasks = tasksRes.status === 'fulfilled' ? tasksRes.value : [];
    const reminders = remindersRes.status === 'fulfilled' ? remindersRes.value : [];
    const todayText = reminderParts(new Date().toISOString()).date;
    this.setData({
      error: errors.join('；'),
      tasks: tasks
        .filter((t) => !t.done && t.due_at && t.due_at.slice(0, 10) <= todayText)
        .map((t) => ({
          ...t,
          checked: false,
          dueText: t.due_at.slice(0, 10),
          overdue: t.due_at.slice(0, 10) < todayText,
        })),
      reminders: reminders
        .filter((r) => !r.done && reminderParts(r.remind_at).date === todayText)
        .map((r) => ({
          ...r,
          remindTime: reminderParts(r.remind_at).time,
        })),
    });
    this.setData({ loading: false });
  },

  async toggleTask(e) {
    const { id, done } = e.currentTarget.dataset;
    try {
      await api.updateTask(id, { done: done ? 0 : 1 });
      await this.loadToday();
    } catch (err) {
      wx.showToast({ title: err.message, icon: 'none' });
    }
  },

  retry() {
    this.loadToday();
  },
});
