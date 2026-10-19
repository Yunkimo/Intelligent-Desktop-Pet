// 课表页：按星期分组展示课程，支持添加/编辑/删除，数据同步到后端 SQLite。
// 非本周课程置灰并标注「本周不上」（weeks 不含当前周；无周次 = 全周）。
const api = require('../../utils/api');
const ws = require('../../utils/ws');
const {
  WEEKDAY_LABELS,
  WEEK_OPTIONS,
  getCurrentWeek,
  setCurrentWeek,
  isActiveWeek,
} = require('../../utils/datetime');

const EMPTY_FORM = {
  id: null,
  name: '',
  day_of_week: 1,
  start_time: '08:00',
  end_time: '09:40',
  location: '',
  teacher: '',
  weeksText: '',
};

// 后端 weeks 存 JSON 字符串（如 "[1,2,3]"），解析并压缩为 "1-3,5" 形式；空返回 ''。
function weeksToText(weeks) {
  let list = weeks;
  if (typeof weeks === 'string') {
    try {
      list = JSON.parse(weeks || '[]');
    } catch (err) {
      list = [];
    }
  }
  list = Array.isArray(list) ? list : [];
  const ranges = [];
  for (const w of list) {
    const last = ranges[ranges.length - 1];
    if (last && w === last.end + 1) {
      last.end = w;
    } else {
      ranges.push({ start: w, end: w });
    }
  }
  return ranges.map((r) => (r.start === r.end ? `${r.start}` : `${r.start}-${r.end}`)).join(',');
}

// 表单周次输入（"1-16" / "1,3,5" / 空=全周）解析为数字数组；格式错误返回 null。
function parseWeeks(text) {
  const raw = String(text || '').trim();
  if (!raw) {
    return [];
  }
  const weeks = [];
  for (const part of raw.split(/[,，、\s]+/)) {
    if (!part) {
      continue;
    }
    const match = part.match(/^(\d+)-(\d+)$/);
    if (match) {
      const start = Number(match[1]);
      const end = Number(match[2]);
      if (start > end) {
        return null;
      }
      for (let w = start; w <= end; w += 1) {
        weeks.push(w);
      }
    } else if (/^\d+$/.test(part)) {
      weeks.push(Number(part));
    } else {
      return null;
    }
  }
  return weeks;
}

Page({
  data: {
    weekOptions: WEEKDAY_LABELS,
    weekPickerOptions: WEEK_OPTIONS,
    currentWeek: 6,
    weekDays: [],
    loading: false,
    error: '',
    editing: false,
    form: { ...EMPTY_FORM },
    pendingCourses: [],
  },

  onShow() {
    this.setData({ currentWeek: getCurrentWeek() });
    ws.on('course.created', this.onWsEvent);
    ws.on('reconnect', this.onWsEvent);
    this.load();
  },

  onHide() {
    ws.off('course.created', this.onWsEvent);
    ws.off('reconnect', this.onWsEvent);
  },

  onUnload() {
    ws.off('course.created', this.onWsEvent);
    ws.off('reconnect', this.onWsEvent);
  },

  // 课表事件到达：REST 重读
  onWsEvent() {
    this.load();
  },

  // 切换本周周次：保存后重新标注各课程是否本周上课
  onWeekPick(e) {
    const week = Number(e.detail.value) + 1;
    setCurrentWeek(week);
    this.setData({ currentWeek: week });
    this.load();
  },

  onPullDownRefresh() {
    this.load().finally(() => wx.stopPullDownRefresh());
  },

  async load() {
    this.setData({ loading: true, error: '' });
    try {
      const courses = await api.getCourses();
      const weekDays = WEEKDAY_LABELS.map((label, i) => ({
        day: i + 1,
        label,
        courses: courses
          .filter((c) => c.day_of_week === i + 1)
          .sort((a, b) => a.start_time.localeCompare(b.start_time))
          .map((c) => ({
            ...c,
            weeksText: weeksToText(c.weeks) || '全周',
            active: isActiveWeek(c, this.data.currentWeek),
          })),
      }));
      this.setData({ weekDays });
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
    const c = e.currentTarget.dataset.course;
    this.setData({
      editing: true,
      form: {
        id: c.id,
        name: c.name,
        day_of_week: c.day_of_week,
        start_time: c.start_time,
        end_time: c.end_time,
        location: c.location || '',
        teacher: c.teacher || '',
        weeksText: weeksToText(c.weeks),
      },
    });
  },

  closeForm() {
    this.setData({ editing: false });
  },

  // 拍照/选图 → 压缩 → 上传识别 → 暂存待确认课程
  async importImage() {
    let tempFilePath = '';
    try {
      const res = await new Promise((resolve, reject) => {
        wx.chooseMedia({
          count: 1,
          mediaType: ['image'],
          sourceType: ['album', 'camera'],
          success: resolve,
          fail: reject,
        });
      });
      tempFilePath = res.tempFiles[0].tempFilePath;
    } catch (err) {
      return; // 用户取消选择，静默返回
    }
    wx.showLoading({ title: '识别中', mask: true });
    try {
      // 压缩控制体积与分辨率：识别速度、流量与 10MB 上限三重保险
      const compressed = await new Promise((resolve, reject) => {
        wx.compressImage({
          src: tempFilePath,
          quality: 60,
          compressedWidth: 1560,
          success: resolve,
          fail: reject,
        });
      });
      const result = await api.parseCourseImage(compressed.tempFilePath);
      wx.hideLoading(); // 先关遮罩再弹提示：真机上遮罩会盖住 toast
      if (!result.courses || result.courses.length === 0) {
        wx.showToast({ title: '未能识别出课程', icon: 'none', duration: 3000 });
        return;
      }
      this.setData({ pendingCourses: result.courses });
      this.confirmImport();
    } catch (err) {
      wx.hideLoading();
      wx.showToast({
        title: (err && err.message) || '识别失败，请重试',
        icon: 'none',
        duration: 3000,
      });
    }
  },

  // 确认弹窗列出课程名+星期+时间（最多 6 行，超出省略）
  confirmImport() {
    const { pendingCourses } = this.data;
    const lines = pendingCourses.slice(0, 6).map(
      (c) => `${c.name}（${WEEKDAY_LABELS[c.day_of_week - 1]} ${c.start_time}-${c.end_time}）`
    );
    const extra = pendingCourses.length > 6 ? `\n……共 ${pendingCourses.length} 节` : '';
    wx.showModal({
      title: `确认导入 ${pendingCourses.length} 节课？`,
      content: lines.join('\n') + extra,
      confirmText: '导入',
      success: async (res) => {
        if (!res.confirm) {
          this.setData({ pendingCourses: [] });
          return;
        }
        wx.showLoading({ title: '导入中', mask: true });
        try {
          const result = await api.bulkCreateCourses(this.data.pendingCourses);
          this.setData({ pendingCourses: [] });
          await this.load();
          const skipped = (result.skipped || []).length;
          wx.showToast({
            title: skipped
              ? `已导入 ${result.created.length} 节，跳过 ${skipped} 节`
              : `已导入 ${result.created.length} 节课`,
            icon: 'none',
          });
          // 首次导入提示设置本周周次：今日页/本页按周次过滤显示
          if (!wx.getStorageSync('current_week')) {
            wx.showModal({
              title: '设置本周周次',
              content: '导入完成！请点顶部「第X周」选择当前是第几周，课表将按周次过滤显示。',
              showCancel: false,
              confirmText: '知道了',
            });
          }
        } catch (err) {
          wx.showToast({ title: err.message, icon: 'none' });
        } finally {
          wx.hideLoading();
        }
      },
    });
  },

  onFormInput(e) {
    const field = e.currentTarget.dataset.field;
    this.setData({ [`form.${field}`]: e.detail.value });
  },

  onWeekPicker(e) {
    this.setData({ 'form.day_of_week': Number(e.detail.value) + 1 });
  },

  async submit() {
    const { form } = this.data;
    if (!form.name.trim()) {
      wx.showToast({ title: '请填写课程名称', icon: 'none' });
      return;
    }
    if (form.start_time >= form.end_time) {
      wx.showToast({ title: '结束时间需晚于开始时间', icon: 'none' });
      return;
    }
    const weeks = parseWeeks(form.weeksText);
    if (weeks === null) {
      wx.showToast({ title: '周次格式不正确（如 1-16 或 1,3,5）', icon: 'none' });
      return;
    }
    const payload = {
      name: form.name.trim(),
      day_of_week: form.day_of_week,
      start_time: form.start_time,
      end_time: form.end_time,
      location: form.location.trim(),
      teacher: form.teacher.trim(),
      weeks,
    };
    wx.showLoading({ title: '保存中' });
    try {
      if (form.id) {
        await api.updateCourse(form.id, payload);
      } else {
        await api.createCourse(payload);
      }
      this.setData({ editing: false });
      await this.load();
    } catch (err) {
      wx.showToast({ title: err.message, icon: 'none' });
    } finally {
      wx.hideLoading();
    }
  },

  remove(e) {
    const { id, name } = e.currentTarget.dataset;
    wx.showModal({
      title: '删除课程',
      content: `确定删除「${name}」吗？后端数据库将同步删除。`,
      success: async (res) => {
        if (!res.confirm) {
          return;
        }
        wx.showLoading({ title: '删除中' });
        try {
          await api.deleteCourse(id);
          wx.showToast({ title: '已删除', icon: 'success' });
        } catch (err) {
          // 删除失败（如服务端已不存在该课程）也刷新列表，避免页面残留陈旧卡片
          wx.showToast({ title: err.message, icon: 'none' });
        } finally {
          wx.hideLoading();
          await this.load();
        }
      },
    });
  },

  retry() {
    this.load();
  },
});
