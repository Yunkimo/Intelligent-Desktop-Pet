// 天气订阅消息落地页：按 event_id 查询本人事件详情（B 契约 weather-subscriptions.md）。
// 经统一登录恢复后读取；非本人或不存在返回 404，不显示他人数据。
const api = require('../../utils/api');
const weather = require('../../utils/weather');

Page({
  data: {
    eventId: '',
    loading: true,
    error: '',
    event: null,
    statusText: '',
    dateLabel: '',
    sentText: '',
  },

  onLoad(options) {
    const eventId = (options && options.event_id) || '';
    this.setData({ eventId });
    this.load();
  },

  onPullDownRefresh() {
    this.load().finally(() => wx.stopPullDownRefresh());
  },

  async load() {
    if (!this.data.eventId) {
      this.setData({ loading: false, error: '缺少事件参数' });
      return;
    }
    this.setData({ loading: true, error: '' });
    try {
      const event = await api.getWeatherSubscription(this.data.eventId);
      this.setData({
        event,
        statusText: weather.statusText(event.status),
        dateLabel: weather.tomorrowLabel(event.target_date),
        sentText: event.sent_at ? '发送时间：' + this.formatTime(event.sent_at) : '',
      });
    } catch (err) {
      this.setData({
        error: err.statusCode === 404 ? '该订阅不存在或不属于当前账号' : err.message || '加载失败',
      });
    } finally {
      this.setData({ loading: false });
    }
  },

  // Unix 秒 → 上海时区 YYYY-MM-DD HH:mm
  formatTime(unixSeconds) {
    const date = new Date(unixSeconds * 1000);
    const pad = (v) => String(v).padStart(2, '0');
    return (
      date.getFullYear() +
      '-' +
      pad(date.getMonth() + 1) +
      '-' +
      pad(date.getDate()) +
      ' ' +
      pad(date.getHours()) +
      ':' +
      pad(date.getMinutes())
    );
  },

  retry() {
    this.load();
  },

  backHome() {
    wx.switchTab({ url: '/pages/index/index' });
  },
});
