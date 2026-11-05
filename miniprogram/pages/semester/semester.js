// 学期设置页：配置第一周的周一与总周数，整体保存到后端（PUT，见 B6 契约）。
// 时区不在此页设置：省略 timezone 时后端默认 Asia/Shanghai。
// C9 起同页展示登录账号（B8 会话）与退出登录入口。
const api = require('../../utils/api');
const semester = require('../../utils/semester');
const session = require('../../utils/session');
const { isMonday } = require('../../utils/datetime');

const WEEK_COUNT_OPTIONS = Array.from({ length: 53 }, (_, i) => `${i + 1} 周`);

function pairingValidity(seconds) {
  if (!Number.isInteger(seconds) || seconds <= 0) {
    return '';
  }
  if (seconds % 86400 === 0) {
    return `${seconds / 86400} 天内有效`;
  }
  if (seconds % 60 === 0) {
    return `${seconds / 60} 分钟内有效`;
  }
  return `${seconds} 秒内有效`;
}

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
    pairingCode: '',
    pairingValidity: '',
    pairingExpiresAt: 0,
    pairingBusy: false,
  },

  onShow() {
    const account = session.accountId() || '';
    this.setData({
      loginAccount: account,
      loggedOut: session.isLoggedOut(),
    });
    if (
      this.data.pairingCode &&
      (this.data.loggedOut || this._pairingOwner !== account || Date.now() >= this.data.pairingExpiresAt)
    ) {
      this.setData({ pairingCode: '', pairingValidity: '', pairingExpiresAt: 0 });
    }
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

  // 手动登录：清除退出标记并换取新会话
  async login() {
    if (this.data.loggingOut) {
      return;
    }
    this.setData({ loggingOut: true });
    try {
      await session.login();
      this.setData({ loggedOut: false, loginAccount: session.accountId() || '' });
      wx.showToast({ title: '已登录', icon: 'success' });
      this.load();
    } catch (err) {
      wx.showToast({ title: (err && err.message) || '登录失败', icon: 'none' });
    } finally {
      this.setData({ loggingOut: false });
    }
  },

  // 有效期由服务端决定，代码始终按字符串保留前导 0。
  async generatePairing() {
    if (this.data.pairingBusy || this.data.loggedOut) {
      return;
    }
    this.setData({ pairingBusy: true, pairingCode: '', pairingValidity: '', pairingExpiresAt: 0 });
    try {
      const result = await api.authPairing();
      if (session.isLoggedOut()) {
        return;
      }
      const validity = pairingValidity(result.expires_in);
      if (typeof result.pairing_code !== 'string' || !result.pairing_code || !validity) {
        wx.showToast({ title: '配对码响应无效，请重试', icon: 'none' });
        return;
      }
      this._pairingOwner = session.accountId() || '';
      this.setData({
        pairingCode: result.pairing_code,
        pairingValidity: validity,
        pairingExpiresAt: Date.now() + result.expires_in * 1000,
      });
      wx.showToast({ title: '配对码已生成', icon: 'none' });
    } catch (err) {
      wx.showToast({ title: (err && err.message) || '生成失败', icon: 'none' });
    } finally {
      this.setData({ pairingBusy: false });
    }
  },

  copyPairing() {
    if (!this.data.pairingCode) {
      return;
    }
    if (
      session.isLoggedOut() ||
      this._pairingOwner !== (session.accountId() || '') ||
      Date.now() >= this.data.pairingExpiresAt
    ) {
      this.setData({ pairingCode: '', pairingValidity: '', pairingExpiresAt: 0 });
      wx.showToast({ title: '请重新生成配对码', icon: 'none' });
      return;
    }
    wx.setClipboardData({ data: this.data.pairingCode });
  },

  // 退出登录：撤销会话、清理账号缓存并返回（业务数据仍归账号，不受影响）
  async logout() {
    if (this.data.loggingOut) {
      return;
    }
    this.setData({ loggingOut: true });
    try {
      const result = await session.logout();
      this.setData({
        loggedOut: true,
        loginAccount: '',
        pairingCode: '',
        pairingValidity: '',
        pairingExpiresAt: 0,
      });
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
