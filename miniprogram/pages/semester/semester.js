// 学期设置页：配置第一周的周一与总周数，整体保存到后端（PUT，见 B6 契约）。
// 时区不在此页设置：省略 timezone 时后端默认 Asia/Shanghai。
// C9 起同页展示登录账号（B8 会话）与退出登录入口。
const semester = require('../../utils/semester');
const session = require('../../utils/session');
const { isMonday } = require('../../utils/datetime');

const WEEK_COUNT_OPTIONS = Array.from({ length: 53 }, (_, i) => `${i + 1} 周`);

Page({
  data: {
    startDate: '',
    weekIndex: 17, // 默认第 18 周（常见学期长度），用户可改
    weekCountOptions: WEEK_COUNT_OPTIONS,
    loading: true,
    saving: false,
    error: '',
    configured: false,
    currentText: '',
    loginAccount: '',
    loggingOut: false,
  },

  onShow() {
    this.setData({ loginAccount: session.accountId() || '' });
    this.load();
  },

  async load() {
    this.setData({ loading: true, error: '' });
    const result = await semester.getSettings();
    if (result.ok && result.configured && result.settings) {
      const s = result.settings;
      this.setData({
        configured: true,
        startDate: s.start_date,
        weekIndex: Math.min(Math.max(s.total_weeks, 1), 53) - 1,
        currentText: `已设置：${s.start_date}（周一）起，共 ${s.total_weeks} 周`,
      });
    } else if (result.ok && !result.configured) {
      this.setData({ configured: false, currentText: '尚未设置学期' });
    } else {
      this.setData({ error: '无法读取学期配置，请检查网络后重试' });
    }
    this.setData({ loading: false });
  },

  onDateChange(e) {
    this.setData({ startDate: e.detail.value });
  },

  onWeekChange(e) {
    this.setData({ weekIndex: Number(e.detail.value) });
  },

  async save() {
    if (this.data.saving) {
      return; // 防连点
    }
    const startDate = this.data.startDate;
    if (!startDate) {
      wx.showToast({ title: '请选择第一周的周一', icon: 'none' });
      return;
    }
    if (!isMonday(startDate)) {
      wx.showToast({ title: '开学日期必须是周一', icon: 'none' });
      return;
    }
    const totalWeeks = Number(this.data.weekIndex) + 1;
    this.setData({ saving: true });
    try {
      const result = await semester.saveSettings({
        start_date: startDate,
        total_weeks: totalWeeks,
      });
      if (!result.ok) {
        wx.showToast({ title: result.error || '保存失败', icon: 'none' });
        return;
      }
      wx.showToast({ title: '学期已保存', icon: 'success' });
      setTimeout(() => wx.navigateBack(), 600);
    } finally {
      this.setData({ saving: false });
    }
  },

  retry() {
    this.load();
  },

  // 退出登录：撤销会话、清理账号缓存并返回（业务数据仍归账号，不受影响）
  async logout() {
    if (this.data.loggingOut) {
      return;
    }
    this.setData({ loggingOut: true });
    try {
      const result = await session.logout();
      wx.showToast({
        title: result.revoked ? '已退出登录' : '已在本机退出（服务端会话稍后失效）',
        icon: 'none',
      });
      setTimeout(() => wx.navigateBack(), 800);
    } catch (err) {
      wx.showToast({ title: (err && err.message) || '退出失败', icon: 'none' });
    } finally {
      this.setData({ loggingOut: false });
    }
  },
});
