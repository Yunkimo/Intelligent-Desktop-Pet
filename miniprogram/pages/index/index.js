// 今日页：展示服务端「今天」的真实周次与当天课表、到期/逾期待办与今日提醒。
// 周次来自 B6 日历接口（按学期设置与配置时区计算），不再是本地固定的 current_week；
// 未设置学期时引导去设置，学期外/离线分别给出可理解的状态。
const api = require('../../utils/api');
const ws = require('../../utils/ws');
const semester = require('../../utils/semester');
const weather = require('../../utils/weather');
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
  'reminder.created',
  'reminder.updated',
  'reminder.deleted',
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
    // 明日带伞提示卡片
    weatherCity: weather.DEFAULT_CITY,
    weatherText: { headline: '', sub: '' },
    weatherDateLabel: '',
    weatherUpdated: '',
    weatherUnknown: false,
    weatherLoading: false,
    weatherSub: null,
    weatherSubText: '',
    weatherBusy: false,
    showCityPicker: false,
    cityInput: '',
    commonCities: weather.COMMON_CITIES,
    weatherEventReady: false,
  },

  onLoad(options) {
    // 微信订阅消息落地：打开本人天气事件详情
    if (options && options.weather_event_id) {
      wx.navigateTo({
        url:
          '/pages/weather-detail/weather-detail?event_id=' +
          encodeURIComponent(options.weather_event_id),
      });
    }
  },

  onShow() {
    WS_EVENTS.forEach((type) => ws.on(type, this.onWsEvent));
    this.scheduleMidnightReload();
    this.loadToday();
    this.loadWeather();
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
    if (event && event.type === 'reconnect') {
      this.loadWeather(); // 断线恢复：天气与订阅状态重读
    }
  },

  onPullDownRefresh() {
    Promise.all([this.loadToday(), this.loadWeather()]).finally(() => wx.stopPullDownRefresh());
  },

  // 跨午夜校准：页面停留时到本地次日 00:00:05 自动重新读取「今天」
  scheduleMidnightReload() {
    if (this._midnightTimer) {
      clearTimeout(this._midnightTimer);
    }
    const now = new Date();
    const next = new Date(now.getFullYear(), now.getMonth(), now.getDate() + 1, 0, 0, 5);
    this._midnightTimer = setTimeout(() => {
      this.loadToday();
      this.loadWeather(); // 跨上海时区午夜：目标日期与事件有效期变化
    }, next.getTime() - now.getTime());
  },

  openSemester() {
    wx.navigateTo({ url: '/pages/semester/semester' });
  },

  // ===== 明日带伞提示：天气卡片 + 微信订阅交互 =====

  // 合并重复请求；旧请求结果不覆盖新城市/新账号结果
  async loadWeather(force) {
    if (this._weatherFlight && !force) {
      return this._weatherFlight;
    }
    const seq = (this._weatherSeq || 0) + 1;
    this._weatherSeq = seq;
    const run = (async () => {
      this.setData({ weatherLoading: true });
      const city = weather.getSavedCity();
      this.setData({ weatherCity: city });
      try {
        const result = await api.getWeatherTomorrow(city);
        if (seq !== this._weatherSeq) {
          return; // 城市已切换：丢弃旧结果
        }
        const text = weather.weatherCardText(result);
        this.setData({
          weatherText: text,
          weatherDateLabel: weather.tomorrowLabel(result.date),
          weatherUpdated: result.fetched_at ? result.fetched_at.slice(11, 16) : '',
          weatherUnknown: result.status === 'unknown',
        });
        // 后台准备本次订阅事件：点击时直接弹授权，不在手势链里异步等待
        this.prepareWeatherEvent(city);
        this.loadWeatherSub();
      } catch (err) {
        if (seq !== this._weatherSeq) {
          return;
        }
        this.setData({
          weatherText: { headline: '天气暂不可用', sub: (err && err.message) || '' },
          weatherUnknown: true,
        });
      } finally {
        this.setData({ weatherLoading: false });
        this._weatherFlight = null;
      }
    })();
    this._weatherFlight = run;
    return run;
  },

  retryWeather() {
    this.loadWeather(true); // 手动重试；后端自带 60 秒退避
  },

  // 准备本次事件（幂等：同用户同城市同目标日期返回同一 event_id）
  async prepareWeatherEvent(city) {
    try {
      const event = await api.weatherPrepare(city);
      this._weatherEvent = { event_id: event.event_id, template_id: event.template_id };
      this.setData({ weatherEventReady: true });
    } catch (err) {
      this._weatherEvent = null;
      this.setData({ weatherEventReady: false });
    }
  },

  // 查询本人订阅状态（最近事件）
  async loadWeatherSub() {
    try {
      const list = await api.getWeatherSubscriptions();
      const current = Array.isArray(list) && list.length > 0 ? list[0] : null;
      this.setData({
        weatherSub: current,
        weatherSubText: current ? weather.statusText(current.status) : '',
      });
      if (current) {
        this._weatherEvent = { event_id: current.event_id, template_id: current.template_id };
        this.setData({ weatherEventReady: true });
      }
    } catch (err) {
      // 订阅状态读取失败不影响天气卡片
      this.setData({ weatherSub: null, weatherSubText: '' });
    }
  },

  // 点击订阅：同步调用微信授权（必须在用户手势链内），随后登记结果
  onSubscribeWeather() {
    if (this.data.weatherBusy) {
      return;
    }
    const event = this._weatherEvent;
    if (!event || !event.template_id) {
      wx.showToast({ title: '订阅事件准备中，请稍候再试', icon: 'none' });
      return;
    }
    // 幂等 request_id：本次点击固定生成，登记不明时用原参数恢复
    const requestId = 'xxxxxxxx-xxxx-4xxx-yxxx-xxxxxxxxxxxx'.replace(/[xy]/g, (c) => {
      const r = (Math.random() * 16) | 0;
      return (c === 'x' ? r : (r & 3) | 8).toString(16);
    });
    wx.requestSubscribeMessage({
      tmplIds: [event.template_id],
      success: async (res) => {
        const choice = res[event.template_id] || 'reject';
        this.setData({ weatherBusy: true });
        try {
          await api.weatherAuthorize(event.event_id, {
            request_id: requestId,
            template_id: event.template_id,
            result: choice,
          });
        } catch (err) {
          wx.showToast({ title: (err && err.message) || '登记失败', icon: 'none', duration: 3000 });
        } finally {
          this.setData({ weatherBusy: false });
          await this.loadWeatherSub();
        }
      },
      fail: (err) => {
        if (/cancel/i.test((err && err.errMsg) || '')) {
          return; // 用户关闭授权弹窗
        }
        wx.showToast({ title: '授权调用失败，请重试', icon: 'none', duration: 3000 });
      },
    });
  },

  // 取消订阅：以服务端状态为准；发送中不可取消（后端 409 提示）
  async cancelWeatherSub() {
    const current = this.data.weatherSub;
    if (!current || this.data.weatherBusy) {
      return;
    }
    this.setData({ weatherBusy: true });
    try {
      await api.cancelWeatherSubscription(current.event_id);
      wx.showToast({ title: '已取消订阅', icon: 'none' });
      await this.loadWeatherSub();
    } catch (err) {
      wx.showToast({ title: (err && err.message) || '取消失败', icon: 'none' });
    } finally {
      this.setData({ weatherBusy: false });
    }
  },

  openWeatherDetail() {
    const current = this.data.weatherSub;
    if (!current) {
      return;
    }
    wx.navigateTo({
      url: '/pages/weather-detail/weather-detail?event_id=' + encodeURIComponent(current.event_id),
    });
  },

  // 城市选择
  openCityPicker() {
    this.setData({ showCityPicker: true, cityInput: this.data.weatherCity });
  },

  closeCityPicker() {
    this.setData({ showCityPicker: false });
  },

  onCityInput(e) {
    this.setData({ cityInput: e.detail.value });
  },

  pickCity(e) {
    this.setData({ cityInput: e.currentTarget.dataset.city });
  },

  async saveCity() {
    const city = weather.normalizeCity(this.data.cityInput);
    if (!city) {
      wx.showToast({ title: '请输入城市名', icon: 'none' });
      return;
    }
    const oldCity = this.data.weatherCity;
    if (city === oldCity) {
      this.setData({ showCityPicker: false });
      return;
    }
    weather.saveCity(city);
    this.setData({ showCityPicker: false });
    const active = ['pending', 'checking', 'retry_weather', 'retry', 'sending', 'sent'];
    if (this.data.weatherSub && active.includes(this.data.weatherSub.status)) {
      wx.showModal({
        title: '切换城市',
        content: `原订阅仍绑定「${oldCity}」，如需改订请先取消原订阅再重新订阅。`,
        showCancel: false,
        confirmText: '知道了',
      });
    }
    this._weatherEvent = null;
    this.setData({ weatherEventReady: false });
    await this.loadWeather(true);
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
