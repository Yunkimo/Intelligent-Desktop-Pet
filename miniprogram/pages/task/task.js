// 日程页：列出全部日程/待办，支持添加/编辑/删除与勾选完成，数据同步到后端 SQLite。
// 独立提醒（一次性 / 每周）也并入本页展示，方便和日程一起查看；挂在日程下的
// 提醒由日程行展示，不重复列出。
// 设置了提醒时间的日程可点「订阅提醒」走微信一次性订阅流程（C3，见 utils/subscribe.js）。
// 一句话创建（C8，B7 契约见 docs/b7-parsing.md）：右下「＋」优先打开文本输入，
// 解析为可确认草稿（缺失/歧义/过去时间标记待确认），确认后逐项 POST /api/tasks
// （后端原子创建 PC 提醒，客户端不额外建提醒）；手动表单保留为修改与失败回退。
const api = require('../../utils/api');
const ws = require('../../utils/ws');
const subscribe = require('../../utils/subscribe');
const taskParse = require('../../utils/task_parse');
const { dateStr, reminderParts, reminderInput } = require('../../utils/datetime');
const { weeklyReminders, oneOffReminders } = require('../../utils/weekly');

// 日程页关心的后端事件（B6 起后端会在其他端增改删时推送更新/删除事件）
const WS_EVENTS = ['task.created', 'task.updated', 'task.deleted', 'reminder.due', 'reminder.created', 'reminder.updated', 'reminder.deleted', 'reconnect'];

function formatInstant(value) {
  const { date, time } = reminderParts(value);
  return date ? date + ' ' + time : '';
}

const EMPTY_FORM = {
  id: null,
  kind: 'task',
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
    captureChoices: [],
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
        key: 'task-' + t.id,
        checked: !!t.done,
        subscriptionText: t.remind_at
          ? stateError
            ? '订阅状态待确认'
            : states[t.id] || '尚未查询或未订阅'
          : '',
        dueText: t.kind === 'schedule'
          ? formatInstant(t.start_at) + (t.end_at ? ' 至 ' + formatInstant(t.end_at) : '')
          : t.due_at ? t.due_at.slice(0, 16).replace('T', ' ') + ' 截止' : '无截止日期',
        remindText: t.remind_at
          ? reminderParts(t.remind_at).date + ' ' + reminderParts(t.remind_at).time
          : '',
        overdue: !!t.due_at && !t.done && t.due_at.slice(0, 10) < today,
      }));
      // 独立提醒并进日程列表：每周固定安排排日程之后，再一次性的提醒。
      // 挂在日程下的提醒（task_id 非空）由日程行展示，不重复列出。
      let weekly = [];
      let oneOff = [];
      try {
        const reminders = await api.getReminders();
        weekly = weeklyReminders(reminders).map((item) => ({
          id: item.id,
          key: 'weekly-' + item.id,
          weekly: true,
          title: item.title,
          note: item.body,
          checked: false,
          overdue: false,
          dueText: '每周' + item.weekday.slice(1) + ' ' + item.time,
          remindText: '',
          subscriptionText: '',
        }));
        oneOff = oneOffReminders(reminders).map((item) => {
          const parts = reminderParts(item.remind_at);
          return {
            id: item.id,
            key: 'reminder-' + item.id,
            reminder: true,
            title: item.title,
            note: item.body,
            checked: false,
            overdue: false,
            dueText: '',
            remindText: parts.date + ' ' + parts.time,
            remind_at: item.remind_at,
            subscriptionText: '',
          };
        });
      } catch (_) {
        /* 提醒读取失败不影响日程列表 */
      }
      this.setData({ tasks: tasks.concat(weekly, oneOff) });
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
        kind: t.reminder ? 'reminder' : t.kind || 'task',
        originalDue: t.due_at,
        originalRemind: t.remind_at,
        start_date: reminderParts(t.start_at).date,
        start_time: reminderParts(t.start_at).time,
        end_date: reminderParts(t.end_at).date,
        end_time: reminderParts(t.end_at).time,
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
    if (form.originalDue && form.originalDue.slice(0, 10) === form.due_at) {
      delete payload.due_at;
    } else if (form.originalDue && form.due_at && form.originalDue.length > 10) {
      payload.due_at = form.due_at + form.originalDue.slice(10);
    }
    const original = reminderParts(form.originalRemind);
    if (form.id && form.kind !== 'reminder' &&
        (original.date || '') === form.remind_date &&
        (!form.remind_date || original.time === form.remind_time)) {
      delete payload.remind_at;
    }
    if (form.kind === 'schedule') {
      if (!form.start_date || !form.start_time || (form.end_date && !form.end_time)) {
        wx.showToast({ title: '请补充日程时间', icon: 'none' });
        return;
      }
      payload.start_at = reminderInput(form.start_date, form.start_time);
      payload.end_at = form.end_date ? reminderInput(form.end_date, form.end_time) : null;
    }
    wx.showLoading({ title: '保存中' });
    try {
      if (form.kind === 'reminder') {
        if (!form.remind_date) {
          wx.hideLoading();
          wx.showToast({ title: '请选择提醒时间', icon: 'none' });
          return;
        }
        await api.updateReminder(form.id, {
          title: payload.title,
          body: payload.note,
          remind_at: reminderInput(form.remind_date, form.remind_time),
        });
      } else if (form.id) {
        await api.updateTask(form.id, payload);
        // 服务端事务处理旧提醒失效；保存成功后仍需主动订阅新事件。
      } else {
        await api.createTask(payload);
      }
      this.setData({ editing: false });
      wx.hideLoading();
      wx.showToast({
        title: form.kind === 'reminder' ? '已保存' : '已保存；改期后请重新订阅',
        icon: 'none',
      });
      await this.load();
    } catch (err) {
      wx.showToast({ title: err.message, icon: 'none' });
    } finally {
      wx.hideLoading();
    }
  },

  stopWeekly(e) {
    const { id, title } = e.currentTarget.dataset;
    wx.showModal({
      title: '停止每周提醒',
      content: `不再每周提醒「${title}」吗？`,
      success: async (res) => {
        if (!res.confirm) {
          return;
        }
        try {
          await api.deleteReminder(id);
          wx.showToast({ title: '已停止', icon: 'success' });
        } catch (err) {
          wx.showToast({ title: err.message, icon: 'none' });
        } finally {
          await this.load();
        }
      },
    });
  },

  async toggleDone(e) {
    const { id, done, kind } = e.currentTarget.dataset;
    try {
      const update = kind === 'reminder' ? api.updateReminder : api.updateTask;
      await update(id, { done: done ? 0 : 1 });
      await this.load();
    } catch (err) {
      wx.showToast({ title: err.message, icon: 'none' });
    }
  },

  remove(e) {
    const { id, title, kind } = e.currentTarget.dataset;
    const isReminder = kind === 'reminder';
    wx.showModal({
      title: isReminder ? '删除提醒' : '删除日程',
      content: isReminder
        ? `确定删除提醒「${title}」吗？`
        : `确定删除「${title}」吗？后端数据库将同步删除。`,
      success: async (res) => {
        if (!res.confirm) {
          return;
        }
        wx.showLoading({ title: '删除中' });
        try {
          if (isReminder) {
            await api.deleteReminder(id);
          } else {
            await api.deleteTask(id);
            // 后端在同一事务中删除任务、关联提醒与订阅。
          }
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
    this._capture = null;
    this._captureStage = 'item';
    this.setData({
      parseStage: '',
      parseText: '',
      captureChoices: [],
      parseFailedText: '',
      draftViews: [],
      draftForm: null,
    });
  },

  onParseTextInput(e) {
    this._capture = null;
    this._captureStage = 'item';
    this.setData({ parseText: e.detail.value, captureChoices: [], parseFailedText: '' });
  },

  // 从文本输入回退到手动表单
  openManualFromText() {
    this.closeParse();
    this.openAdd();
  },

  // 解析：防连点；失败保留原文可重试
  async captureText() {
    if (this.data.parsing) return;
    const text = this.data.parseText.trim();
    if (!text) {
      wx.showToast({ title: '请输入事项', icon: 'none' });
      return;
    }
    if (!this._capture || this._capture.text !== text) {
      this._captureStage = 'item';
      this._capture = {
        text,
        request_id: Date.now().toString(36) + '-' + Math.random().toString(36).slice(2),
        timezone: taskParse.buildReference().timezone,
      };
    }
    await this.runCapture(() => api.captureText(this._capture));
  },

  async chooseCapture(e) {
    if (!this._capture || this.data.parsing) return;
    const option = Number(e.currentTarget.dataset.option);
    await this.runCapture(() => api.confirmCapture(this._capture.request_id, option, this._captureStage));
  },

  async runCapture(send) {
    this.setData({ parsing: true, parseFailedText: '' });
    const capture = this._capture;
    try {
      const result = await send();
      if (this._capture !== capture) return;
      if (result.status === 'created') {
        this.closeParse();
        wx.showToast({ title: '已添加' + { todo: '待办', schedule: '日程', reminder: '提醒' }[result.kind], icon: 'none' });
        await this.load();
      } else {
        this._captureStage = result.stage || 'item';
        this.setData({ parseFailedText: result.message, captureChoices: result.choices || [] });
      }
    } catch (err) {
      if (this._capture === capture) {
        this.setData({ parseFailedText: err.message || '提交失败，请重试' });
      }
    } finally {
      this.setData({ parsing: false });
    }
  },

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
