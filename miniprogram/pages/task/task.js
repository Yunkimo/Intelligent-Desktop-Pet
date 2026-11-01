// 日程页：列出全部日程/待办，支持添加/编辑/删除与勾选完成，数据同步到后端 SQLite。
// 设置了提醒时间的日程可点「订阅提醒」走微信一次性订阅流程（C3，见 utils/subscribe.js）。
// 一句话创建（C8，B7 契约见 docs/b7-parsing.md）：右下「＋」优先打开文本输入，
// 解析为可确认草稿（缺失/歧义/过去时间标记待确认），确认后逐项 POST /api/tasks
// （后端原子创建 PC 提醒，客户端不额外建提醒）；手动表单保留为修改与失败回退。
const api = require('../../utils/api');
const ws = require('../../utils/ws');
const subscribe = require('../../utils/subscribe');
const taskParse = require('../../utils/task_parse');
const { dateStr, reminderParts, reminderInput } = require('../../utils/datetime');

// 日程页关心的后端事件（B6 起后端会在其他端增改删时推送更新/删除事件）
const WS_EVENTS = ['task.created', 'task.updated', 'task.deleted', 'reminder.due', 'reconnect'];

const EMPTY_FORM = {
  id: null,
  title: '',
  note: '',
  due_at: '',
  remind_date: '',
  remind_time: '08:00',
};

const EMPTY_DRAFT_FORM = {
  index: -1,
  title: '',
  note: '',
  due_at: '',
  remind_date: '',
  remind_time: '08:00',
};

// 草稿 → 列表视图模型（保留原文与时间提示，缺项/过去时间标记待确认）
function draftViews(drafts) {
  return drafts.map((draft, index) => ({
    index,
    title: draft.title,
    note: draft.note,
    dueText: draft.due_at ? '截止 ' + draft.due_at.slice(0, 10) : '',
    remindText: draft.remind_at
      ? '提醒 ' + reminderParts(draft.remind_at).date + ' ' + reminderParts(draft.remind_at).time
      : '',
    needsText: taskParse.needsText(draft),
  }));
}

Page({
  data: {
    tasks: [],
    loading: false,
    error: '',
    editing: false,
    subscribingId: null,
    form: { ...EMPTY_FORM },
    // 一句话创建状态机：'' / 'input' / 'draft'
    parseStage: '',
    parseText: '',
    parsing: false,
    savingDrafts: false,
    parseFailedText: '',
    draftViews: [],
    draftForm: null,
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
      let states = {};
      let stateError = false;
      try {
        states = await subscribe.subscriptionStates();
      } catch (_) {
        stateError = true;
      }
      const tasks = (await api.getTasks()).map((t) => ({
        ...t,
        checked: !!t.done,
        subscriptionText: t.remind_at
          ? stateError
            ? '订阅状态待确认'
            : states[t.id] || '尚未查询或未订阅'
          : '',
        dueText: t.due_at ? t.due_at.slice(0, 10) : '无截止日期',
        remindText: t.remind_at
          ? reminderParts(t.remind_at).date + ' ' + reminderParts(t.remind_at).time
          : '',
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
        remind_date: reminderParts(t.remind_at).date,
        remind_time: reminderParts(t.remind_at).time || '08:00',
      },
    });
  },

  closeForm() {
    this.setData({ editing: false });
  },

  clearReminder() {
    this.setData({ 'form.remind_date': '' });
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
      remind_at: form.remind_date ? reminderInput(form.remind_date, form.remind_time) : null,
    };
    wx.showLoading({ title: '保存中' });
    try {
      if (form.id) {
        await api.updateTask(form.id, payload);
        // 服务端事务处理旧提醒失效；保存成功后仍需主动订阅新事件。
      } else {
        await api.createTask(payload);
      }
      this.setData({ editing: false });
      wx.hideLoading();
      wx.showToast({ title: '已保存；改期后请重新订阅', icon: 'none' });
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
          // 后端在同一事务中删除任务、关联提醒与订阅。
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
    if (this.data.subscribingId != null) {
      return;
    }
    this.setData({ subscribingId: task.id });
    wx.showLoading({ title: '处理中', mask: true });
    try {
      const result = await subscribe.subscribeTaskReminder(task);
      wx.hideLoading(); // 先关遮罩再弹 toast：真机上遮罩会盖住 toast
      if (result.status === 'cancel') {
        return; // 用户关闭授权弹窗：静默，不落库不提示
      }
      wx.showToast({ title: result.message || '订阅处理完成', icon: 'none', duration: 3000 });
      await this.load();
    } catch (err) {
      wx.hideLoading();
      wx.showToast({
        title: (err && err.message) || '操作失败，请重试',
        icon: 'none',
        duration: 3000,
      });
    } finally {
      this.setData({ subscribingId: null });
    }
  },

  retry() {
    this.load();
  },

  // ===== 一句话创建（C8）=====

  // 新增入口：优先文本输入，手动表单作为回退（从草稿返回时保留原文可修改）
  openTextInput() {
    this.setData({ parseStage: 'input', parseFailedText: '' });
  },

  closeParse() {
    this._drafts = null;
    this.setData({
      parseStage: '',
      parseText: '',
      parseFailedText: '',
      draftViews: [],
      draftForm: null,
    });
  },

  onParseTextInput(e) {
    this.setData({ parseText: e.detail.value });
  },

  // 从文本输入回退到手动表单
  openManualFromText() {
    this.closeParse();
    this.openAdd();
  },

  // 解析：防连点；失败保留原文可重试
  async parseText() {
    if (this.data.parsing) {
      return;
    }
    const text = this.data.parseText.trim();
    if (!text) {
      wx.showToast({ title: '请输入日程内容', icon: 'none' });
      return;
    }
    this.setData({ parsing: true, parseFailedText: '' });
    try {
      const result = await api.parseTaskText({ ...taskParse.buildReference(), text });
      const drafts = (result && result.drafts) || [];
      if (drafts.length === 0) {
        this.setData({ parseFailedText: '未能解析出日程，请调整描述' });
        return;
      }
      this._drafts = drafts;
      this.setData({
        parseStage: 'draft',
        draftViews: draftViews(drafts),
        draftForm: null,
      });
    } catch (err) {
      this.setData({ parseFailedText: (err && err.message) || '解析失败，请重试' });
    } finally {
      this.setData({ parsing: false });
    }
  },

  // 草稿编辑（复用字段布局；保存只更新本地草稿，不落库）
  openDraftForm(e) {
    const index = e.currentTarget.dataset.index;
    const draft = this._drafts[index];
    this.setData({
      draftForm: {
        ...EMPTY_DRAFT_FORM,
        index,
        title: draft.title || '',
        note: draft.note || '',
        due_at: draft.due_at ? draft.due_at.slice(0, 10) : '',
        remind_date: draft.remind_at ? reminderParts(draft.remind_at).date : '',
        remind_time: draft.remind_at ? reminderParts(draft.remind_at).time : '08:00',
      },
    });
  },

  closeDraftForm() {
    this.setData({ draftForm: null });
  },

  onDraftFormInput(e) {
    const field = e.currentTarget.dataset.field;
    this.setData({ [`draftForm.${field}`]: e.detail.value });
  },

  clearDraftReminder() {
    this.setData({ 'draftForm.remind_date': '' });
  },

  saveDraftForm() {
    const form = this.data.draftForm;
    if (!form.title.trim()) {
      wx.showToast({ title: '请填写标题', icon: 'none' });
      return;
    }
    const draft = this._drafts[form.index];
    this._drafts[form.index] = {
      ...draft,
      title: form.title.trim(),
      note: form.note.trim(),
      due_at: form.due_at || null,
      remind_at: form.remind_date ? reminderInput(form.remind_date, form.remind_time) : null,
    };
    this.setData({ draftForm: null, draftViews: draftViews(this._drafts) });
  },

  // 从草稿中移除一条（不落库）
  removeDraft(e) {
    const index = e.currentTarget.dataset.index;
    this._drafts.splice(index, 1);
    if (this._drafts.length === 0) {
      this.closeParse();
      return;
    }
    this.setData({ draftViews: draftViews(this._drafts) });
  },

  // 确认保存：逐项 POST /api/tasks，失败/待确认项保留可重试，不整批盲重放
  async confirmParseSave() {
    if (this.data.savingDrafts) {
      return; // 防连点
    }
    const drafts = this._drafts || [];
    if (drafts.length === 0) {
      return;
    }
    this.setData({ savingDrafts: true });
    wx.showLoading({ title: '保存中', mask: true });
    try {
      const { statuses } = await taskParse.saveDrafts(drafts, api);
      wx.hideLoading();
      await this.load(); // 保存后从真实后端读回（提醒状态以服务端为准）
      const created = statuses.filter((s) => s.status === 'created').length;
      const failed = taskParse.failedDrafts(statuses);
      if (failed.length > 0) {
        // 失败/待确认项保留原文与草稿，供修正后重试
        this._drafts = failed;
        this.setData({
          draftViews: draftViews(failed),
          parseFailedText: `已保存 ${created} 条，${failed.length} 条未成功，请核对后重试`,
        });
        wx.showToast({
          title: `已保存 ${created} 条，${failed.length} 条未成功`,
          icon: 'none',
          duration: 3000,
        });
        return;
      }
      this.closeParse();
      wx.showToast({ title: `已保存 ${created} 条日程`, icon: 'none' });
    } catch (err) {
      wx.hideLoading();
      wx.showToast({ title: err.message || '保存失败', icon: 'none' });
    } finally {
      this.setData({ savingDrafts: false });
    }
  },
});
