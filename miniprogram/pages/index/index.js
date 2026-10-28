// 今日页：展示今天的课表与到期/逾期待办，支持勾选完成。
// 课表按「本周周次」过滤：weeks 不含当前周的课程不显示（无周次 = 全周）。
const api = require('../../utils/api');
const ws = require('../../utils/ws');
const {
  WEEKDAY_LABELS,
  WEEK_OPTIONS,
  todayDow,
  getCurrentWeek,
  setCurrentWeek,
  isActiveWeek,
  reminderParts,
} = require('../../utils/datetime');

// 今日页关心的后端事件（WebSocket 推送后 REST 重读，节流由 ws.js 统一处理）
const WS_EVENTS = ['task.created', 'course.created', 'reminder.due', 'reconnect'];

Page({
  data: {
    currentWeek: 6,
    weekOptions: WEEK_OPTIONS,
    todayLabel: '',
    courses: [],
    tasks: [],
    reminders: [],
    loading: false,
    error: '',
  },

  onShow() {
    this.setData({ currentWeek: getCurrentWeek() });
    WS_EVENTS.forEach((type) => ws.on(type, this.onWsEvent));
    this.loadToday();
  },

  onHide() {
    WS_EVENTS.forEach((type) => ws.off(type, this.onWsEvent));
  },

  onUnload() {
    WS_EVENTS.forEach((type) => ws.off(type, this.onWsEvent));
  },

  // 后端事件到达：REST 重读（onShow 也走这里，覆盖断线恢复）
  onWsEvent(event) {
    if (event && event.type === 'reminder.due') {
      wx.showToast({ title: '有提醒到期', icon: 'none', duration: 3000 });
    }
    this.loadToday();
  },

  onPullDownRefresh() {
    this.loadToday().finally(() => wx.stopPullDownRefresh());
  },

  // 切换本周周次：保存后按新周次重新过滤
  onWeekPick(e) {
    const week = Number(e.detail.value) + 1;
    setCurrentWeek(week);
    this.setData({ currentWeek: week });
    this.loadToday();
  },

  async loadToday() {
    this.setData({ loading: true, error: '' });
    try {
      const [courses, tasks, reminders] = await Promise.all([
        api.getCourses(),
        api.getTasks(),
        api.getReminders(),
      ]);
      const dow = todayDow();
      const today = reminderParts(new Date().toISOString()).date;
      this.setData({
        todayLabel: `第${this.data.currentWeek}周 · ${WEEKDAY_LABELS[dow - 1]} · ${today}`,
        courses: courses
          .filter((c) => c.day_of_week === dow && isActiveWeek(c, this.data.currentWeek))
          .sort((a, b) => a.start_time.localeCompare(b.start_time)),
        tasks: tasks
          .filter((t) => !t.done && t.due_at && t.due_at.slice(0, 10) <= today)
          .map((t) => ({
            ...t,
            checked: false,
            dueText: t.due_at.slice(0, 10),
            overdue: t.due_at.slice(0, 10) < today,
          })),
        reminders: reminders
          .filter((r) => !r.done && reminderParts(r.remind_at).date === today)
          .map((r) => ({
            ...r,
            remindTime: reminderParts(r.remind_at).time,
          })),
      });
    } catch (err) {
      this.setData({ error: err.message || '加载失败' });
    } finally {
      this.setData({ loading: false });
    }
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
