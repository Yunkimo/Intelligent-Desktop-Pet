// 日程页：列出全部日程/待办，支持添加/编辑/删除与勾选完成，数据同步到后端 SQLite。
// 设置了提醒时间的日程可点「订阅提醒」走微信一次性订阅流程（C3，见 utils/subscribe.js）。
const api = require('../../utils/api');
const ws = require('../../utils/ws');
const subscribe = require('../../utils/subscribe');
const { dateStr } = require('../../utils/datetime');

// 日程页关心的后端事件
const WS_EVENTS = ['task.created', 'reminder.due', 'reconnect'];

const EMPTY_FORM = {
  id: null,
  title: '',
  note: '',
  due_at: '',
  remind_date: '',
  remind_time: '08:00',
};

Page({
  data: {
    tasks: [],
    loading: false,
    error: '',
    editing: false,
    form: { ...EMPTY_FORM },
  },

  onShow() {
    WS_EVENTS.forEach((type) => ws.on(type, this.onWsEvent));
    this.load();
  },

  onHide() {
    WS_EVENTS.forEach((type) => ws.off(type, this.onWsEvent));
  },

  onUnload() {
    WS_EVENTS.forEach((type) => ws.off(type, this.onWsEvent));
  },

  // 日程事件到达：REST 重读
  onWsEvent() {
    this.load();
  },

  onPullDownRefresh() {
    this.load().finally(() => wx.stopPullDownRefresh());
  },

  async load() {
    this.setData({ loading: true, error: '' });
    try {
      const today = dateStr(new Date());
      const tasks = (await api.getTasks()).map((t) => ({
        ...t,
        checked: !!t.done,
        dueText: t.due_at ? t.due_at.slice(0, 10) : '无截止日期',
        remindText: t.remind_at ? t.remind_at.slice(0, 16).replace('T', ' ') : '',
        overdue: !!t.due_at && !t.done && t.due_at.slice(0, 10) < today,
      }));
      this.setData({ tasks });
    } catch (err) {
      this.setData({ error: err.message || '加载失败' });
    } finally {
      this.setData({ loading: false });
    }
  },

  openAdd() {
    this.setData({ editing: true, form: { ...EMPTY_FORM } });
  },

  openEdit(e) {
    const t = e.currentTarget.dataset.task;
    this.setData({
      editing: true,
      form: {
        id: t.id,
        title: t.title,
        note: t.note || '',
        due_at: t.due_at ? t.due_at.slice(0, 10) : '',
        remind_date: t.remind_at ? t.remind_at.slice(0, 10) : '',
        remind_time: t.remind_at ? t.remind_at.slice(11, 16) : '08:00',
      },
    });
  },

  closeForm() {
    this.setData({ editing: false });
  },

  onFormInput(e) {
    const field = e.currentTarget.dataset.field;
    this.setData({ [`form.${field}`]: e.detail.value });
  },

  async submit() {
    const { form } = this.data;
    if (!form.title.trim()) {
      wx.showToast({ title: '请填写标题', icon: 'none' });
      return;
    }
    const payload = {
      title: form.title.trim(),
      note: form.note.trim(),
      due_at: form.due_at || null,
      // 提醒时间：日期+时间合并为 "YYYY-MM-DDTHH:MM"（无时区，后端按 UTC+8 兼容处理）
      remind_at: form.remind_date ? `${form.remind_date}T${form.remind_time}` : null,
    };
    wx.showLoading({ title: '保存中' });
    try {
      if (form.id) {
        await api.updateTask(form.id, payload);
        // 编辑后提醒时间可能已变：清除本地订阅标记，允许（且需要）重新订阅
        wx.removeStorageSync('sub_flag_' + form.id);
      } else {
        await api.createTask(payload);
      }
      this.setData({ editing: false });
      await this.load();
    } catch (err) {
      wx.showToast({ title: err.message, icon: 'none' });
    } finally {
      wx.hideLoading();
    }
  },

  async toggleDone(e) {
    const { id, done } = e.currentTarget.dataset;
    try {
      await api.updateTask(id, { done: done ? 0 : 1 });
      await this.load();
    } catch (err) {
      wx.showToast({ title: err.message, icon: 'none' });
    }
  },

  remove(e) {
    const { id, title } = e.currentTarget.dataset;
    wx.showModal({
      title: '删除日程',
      content: `确定删除「${title}」吗？后端数据库将同步删除。`,
      success: async (res) => {
        if (!res.confirm) {
          return;
        }
        wx.showLoading({ title: '删除中' });
        try {
          await api.deleteTask(id);
          wx.showToast({ title: '已删除', icon: 'success' });
        } catch (err) {
          // 删除失败（如服务端已不存在该日程）也刷新列表，避免页面残留陈旧卡片
          wx.showToast({ title: err.message, icon: 'none' });
        } finally {
          wx.hideLoading();
          await this.load();
        }
      },
    });
  },

  // 订阅提醒（C3）：用户主动点击触发微信一次性订阅授权，流程见 utils/subscribe.js
  async subscribeTask(e) {
    const task = e.currentTarget.dataset.task;
    wx.showLoading({ title: '处理中', mask: true });
    try {
      const result = await subscribe.subscribeTaskReminder(task);
      if (result.status === 'cancel') {
        return; // 用户关闭授权弹窗：静默，不落库不提示
      }
      wx.showToast({ title: result.message || '订阅处理完成', icon: 'none', duration: 3000 });
    } catch (err) {
      wx.showToast({ title: (err && err.message) || '操作失败，请重试', icon: 'none' });
    } finally {
      wx.hideLoading();
    }
  },

  retry() {
    this.load();
  },
});
