// 课表页：按星期分组展示课程，支持添加/编辑/删除与图片识别导入，数据同步到后端 SQLite。
// 周次口径与今日页一致（B6 学期设置）：顶部选择器仅用于「浏览其他周」，不改学期配置、
// 不写入本地存储；重新进入页面默认回到真实本周。浏览周内不上课的课程置灰。
// 图片导入（C7，B7 契约见 docs/b7-parsing.md）：上传前预览压缩 → 上传阶段显示真实
// 已等待秒数（不伪造百分比）→ 可编辑草稿与警告 → 缺时间先按节次映射 → 确认后逐条
// 核对保存结果，部分失败只恢复失败项。取消/超时/退出不残留转圈。
const api = require('../../utils/api');
const ws = require('../../utils/ws');
const semester = require('../../utils/semester');
const courseImport = require('../../utils/course_import');
const { WEEKDAY_LABELS, isActiveWeek, weekNumberOptions } = require('../../utils/datetime');

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

// 草稿 → 列表视图模型（时间/星期/周次缺失提示）
function draftViews(drafts) {
  return drafts.map((draft, index) => {
    const needs = courseImport.missingFields(draft);
    const needsText = needs
      .map((n) => (n === 'time' ? '缺时间' : n === 'weeks' ? '缺周次' : '缺星期'))
      .join('、');
    const timeText =
      draft.start_time && draft.end_time ? `${draft.start_time}-${draft.end_time}` : '--:--';
    const dayText = Number.isInteger(draft.day_of_week)
      ? WEEKDAY_LABELS[draft.day_of_week - 1]
      : '周?';
    return {
      index,
      name: draft.name,
      meta: `${dayText} · ${timeText}${draft.location ? ' · ' + draft.location : ''}${
        draft.teacher ? ' · ' + draft.teacher : ''
      }`,
      weeksText: draft.weeks == null ? '周次待定' : weeksToText(draft.weeks) || '全周',
      slotText: draft.slot ? `节次：${draft.slot}` : '',
      needsText,
      incomplete: needs.length > 0,
    };
  });
}

Page({
  data: {
    weekOptions: WEEKDAY_LABELS,
    weekPickerOptions: weekNumberOptions(25),
    browseWeek: 1,
    realWeek: null,
    isBrowsing: false,
    statusText: '',
    needSetup: false,
    offline: false,
    weekDays: [],
    loading: false,
    error: '',
    editing: false,
    form: { ...EMPTY_FORM },
    // 图片导入状态机：'' / 'uploading' / 'draft' / 'slot'
    importStage: '',
    importElapsed: 0,
    importFailedText: '',
    warnings: [],
    hasPendingSlots: false,
    draftViews: [],
    draftForm: null,
    slotList: [],
    slotForms: [],
  },

  onShow() {
    // 重新进入默认回到本周：load() 内会把 browseWeek 重置为真实周
    ws.on('course.created', this.onWsEvent);
    ws.on('course.updated', this.onWsEvent);
    ws.on('course.deleted', this.onWsEvent);
    ws.on('semester.updated', this.onWsEvent);
    ws.on('reconnect', this.onWsEvent);
    this.load();
  },

  onHide() {
    ws.off('course.created', this.onWsEvent);
    ws.off('course.updated', this.onWsEvent);
    ws.off('course.deleted', this.onWsEvent);
    ws.off('semester.updated', this.onWsEvent);
    ws.off('reconnect', this.onWsEvent);
  },

  onUnload() {
    this.onHide();
    this.cancelUpload(); // 退出页面：中止可中止的请求并清理计时器
  },

  // 课表/学期事件到达：REST 重读（删除事件后读列表，不请求已删除的详情）
  onWsEvent() {
    this.load();
  },

  // 浏览其他周：仅切换页面展示，不修改学期配置、不写本地存储
  onWeekPick(e) {
    const week = Number(e.detail.value) + 1;
    this.setData({ browseWeek: week, isBrowsing: week !== this.data.realWeek });
    this.applyCourses();
  },

  // 回到本周
  backToThisWeek() {
    this.setData({ browseWeek: this.data.realWeek || 1, isBrowsing: false });
    this.applyCourses();
  },

  openSemester() {
    wx.navigateTo({ url: '/pages/semester/semester' });
  },

  onPullDownRefresh() {
    this.load().finally(() => wx.stopPullDownRefresh());
  },

  async load() {
    this.setData({ loading: true, error: '' });
    try {
      const today = await semester.getToday();
      const settingsResult = await semester.getSettings();
      const totalWeeks =
        settingsResult.ok && settingsResult.settings
          ? settingsResult.settings.total_weeks
          : (today.settings && today.settings.total_weeks) || 25;
      const realWeek = today.ok && today.status === 'in_term' ? today.week : null;
      const statusText = !today.ok
        ? '无法确认学期（网络不可达）'
        : today.status !== 'in_term'
          ? today.status === 'unconfigured'
            ? '未设置学期'
            : today.status === 'before_term'
              ? '当前在学期开始前'
              : '当前在学期结束后'
          : '';
      this.setData({
        weekPickerOptions: weekNumberOptions(totalWeeks),
        browseWeek: realWeek || 1,
        realWeek,
        isBrowsing: false,
        statusText,
        needSetup: today.ok && today.status === 'unconfigured',
        offline: !!today.offline,
      });
      let courses = [];
      try {
        courses = await api.getCourses();
      } catch (err) {
        // 离线时课表列表不可用：保留已计算好的周次并提示
        this.setData({ weekDays: [], error: '课程列表加载失败：' + (err.message || '请检查网络') });
        return;
      }
      this.setData({ allCourses: courses });
      this.applyCourses();
    } catch (err) {
      this.setData({ error: err.message || '加载失败' });
    } finally {
      this.setData({ loading: false });
    }
  },

  // 按当前浏览周把课程按星期分组并标注是否该周上课
  applyCourses() {
    const courses = this.data.allCourses || [];
    const browseWeek = this.data.browseWeek;
    const weekDays = WEEKDAY_LABELS.map((label, i) => ({
      day: i + 1,
      label,
      courses: courses
        .filter((c) => c.day_of_week === i + 1)
        .sort((a, b) => a.start_time.localeCompare(b.start_time))
        .map((c) => ({
          ...c,
          weeksText: weeksToText(c.weeks) || '全周',
          active: isActiveWeek(c, browseWeek),
        })),
    }));
    this.setData({ weekDays });
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

  // ===== 图片识别导入（C7）=====

  // 中止上传请求并清理计时器（取消/超时/退出共用）
  cancelUpload() {
    if (this._upload) {
      this._upload.abort();
      this._upload = null;
    }
    this._importSeq = (this._importSeq || 0) + 1; // 迟到响应一律按旧请求丢弃
    if (this._importTimer) {
      clearInterval(this._importTimer);
      this._importTimer = null;
    }
  },

  // 选图 → 预览 → 压缩 → 上传识别 → 草稿确认
  async importImage() {
    if (this.data.importStage !== '') {
      return; // 已在流程中，禁止重复点击
    }
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
    // 上传前预览：让用户确认图源清晰（文字不糊）
    await new Promise((resolve) => {
      wx.previewImage({ urls: [tempFilePath], success: resolve, fail: resolve });
    });
    let filePath = tempFilePath;
    try {
      // 适度压缩：不把文字压糊（B7 建议控制清晰度与体积，上限 10MB/1600 万像素）
      const compressed = await new Promise((resolve, reject) => {
        wx.compressImage({
          src: tempFilePath,
          quality: 80,
          compressedWidth: 1920,
          success: resolve,
          fail: reject,
        });
      });
      filePath = compressed.tempFilePath;
    } catch (err) {
      /* 压缩失败用原图继续 */
    }
    this.startUpload(filePath);
  },

  // 上传阶段：显示真实阶段与已等待秒数（不伪造百分比），支持取消；70 秒超时
  startUpload(filePath) {
    const seq = (this._importSeq || 0) + 1;
    this._importSeq = seq;
    this.setData({ importStage: 'uploading', importElapsed: 0, importFailedText: '' });
    this._importTimer = setInterval(() => {
      this.setData({ importElapsed: this.data.importElapsed + 1 });
    }, 1000);
    this._upload = api.uploadWithTask('/api/courses/parse-image', { filePath, name: 'image' });
    this._upload.done
      .then(async (result) => {
        if (seq !== this._importSeq) {
          return; // 已取消/已超时/已退出：丢弃迟到结果
        }
        clearInterval(this._importTimer);
        this._importTimer = null;
        this._upload = null;
        await this.showDrafts(result);
      })
      .catch((err) => {
        if (seq !== this._importSeq) {
          return; // 已取消/已超时：静默忽略
        }
        clearInterval(this._importTimer);
        this._importTimer = null;
        this._upload = null;
        if (err && err.cancelled) {
          this.setData({ importStage: '' });
          wx.showToast({ title: '已取消识别', icon: 'none' });
          return;
        }
        const text =
          err && err.timeout
            ? '识别超时（已等 70 秒），可重试'
            : (err && err.message) || '识别失败，请重试';
        // 失败停留可重试状态（保留 70 秒后自动收起的提示）
        this.setData({ importStage: '', importFailedText: text });
        wx.showToast({ title: text, icon: 'none', duration: 3000 });
      });
  },

  // 用户点「取消」：中止上传，不宣称上游计算与费用已撤销
  cancelImportUpload() {
    this.cancelUpload();
    this.setData({ importStage: '' });
    wx.showToast({ title: '已取消识别', icon: 'none' });
  },

  // 识别完成：合并 courses 与 pending_courses 展示可编辑草稿与警告
  async showDrafts(result) {
    const drafts = courseImport.mergeDrafts(result);
    if (drafts.length === 0) {
      this.setData({ importStage: '' });
      wx.showToast({ title: '未能识别出课程，请上传清晰的课表截图', icon: 'none', duration: 3000 });
      return;
    }
    this._drafts = drafts;
    this.setData({
      importStage: 'draft',
      warnings: result.warnings || [],
      hasPendingSlots: courseImport.pendingSlots(drafts).length > 0,
      draftViews: draftViews(drafts),
      draftForm: null,
      slotForms: [],
    });
  },

  // 关闭草稿弹窗（放弃本次识别结果，未落库）
  cancelDraftImport() {
    this._drafts = null;
    this.setData({
      importStage: '',
      warnings: [],
      hasPendingSlots: false,
      draftViews: [],
      draftForm: null,
      slotList: [],
      slotForms: [],
    });
  },

  // 打开草稿编辑表单
  openDraftForm(e) {
    const index = e.currentTarget.dataset.index;
    const draft = this._drafts[index];
    this.setData({
      draftForm: {
        index,
        name: draft.name,
        day_of_week: Number.isInteger(draft.day_of_week) ? draft.day_of_week : 1,
        start_time: draft.start_time || '',
        end_time: draft.end_time || '',
        location: draft.location || '',
        teacher: draft.teacher || '',
        weeksText: draft.weeks == null ? '' : weeksToText(draft.weeks),
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

  onDraftWeekPicker(e) {
    this.setData({ 'draftForm.day_of_week': Number(e.detail.value) + 1 });
  },

  // 保存单条草稿的修改
  saveDraftForm() {
    const form = this.data.draftForm;
    if (!form.name.trim()) {
      wx.showToast({ title: '请填写课程名称', icon: 'none' });
      return;
    }
    if (form.start_time && form.end_time && form.start_time >= form.end_time) {
      wx.showToast({ title: '结束时间需晚于开始时间', icon: 'none' });
      return;
    }
    const weeks = parseWeeks(form.weeksText);
    if (weeks === null) {
      wx.showToast({ title: '周次格式不正确（如 1-16 或 1,3,5）', icon: 'none' });
      return;
    }
    const draft = this._drafts[form.index];
    this._drafts[form.index] = {
      ...draft,
      name: form.name.trim(),
      day_of_week: form.day_of_week,
      start_time: form.start_time || null,
      end_time: form.end_time || null,
      location: form.location.trim(),
      teacher: form.teacher.trim(),
      weeks,
    };
    this.setData({
      draftForm: null,
      hasPendingSlots: courseImport.pendingSlots(this._drafts).length > 0,
      draftViews: draftViews(this._drafts),
    });
  },

  // 从草稿中移除一条（不落库，仅影响本次导入）
  removeDraft(e) {
    const index = e.currentTarget.dataset.index;
    this._drafts.splice(index, 1);
    if (this._drafts.length === 0) {
      this.cancelDraftImport();
      return;
    }
    this.setData({
      hasPendingSlots: courseImport.pendingSlots(this._drafts).length > 0,
      draftViews: draftViews(this._drafts),
    });
  },

  // 节次时间映射：已按标准节次时间预填，可统一修改后应用（草稿单条也可改）
  openSlotModal() {
    const slots = courseImport.pendingSlots(this._drafts);
    this.setData({
      importStage: 'slot',
      slotList: slots,
      slotForms: slots.map((slot) => {
        const defaultTime = courseImport.defaultSlotTime(slot);
        return {
          slot,
          start: defaultTime ? defaultTime.start : '',
          end: defaultTime ? defaultTime.end : '',
        };
      }),
    });
  },

  closeSlotModal() {
    this.setData({ importStage: 'draft' });
  },

  onSlotFormInput(e) {
    const { index, field } = e.currentTarget.dataset;
    this.setData({ [`slotForms[${index}].${field}`]: e.detail.value });
  },

  // 应用节次映射：仍缺时间的条目（无节次标签等）需回到草稿手工补
  saveSlotMapping() {
    const mapping = {};
    let invalid = 0;
    this.data.slotForms.forEach((row) => {
      if (!row.start || !row.end || row.start >= row.end) {
        invalid += 1;
        return;
      }
      mapping[row.slot] = { start: row.start, end: row.end };
    });
    if (invalid > 0) {
      wx.showToast({ title: `还有 ${invalid} 个节次未填或时间无效`, icon: 'none' });
      return;
    }
    this._drafts = courseImport.applySlotMapping(this._drafts, mapping);
    this.setData({
      importStage: 'draft',
      hasPendingSlots: courseImport.pendingSlots(this._drafts).length > 0,
      draftViews: draftViews(this._drafts),
    });
  },

  // 确认导入：全部补全后才允许保存；保存后按实际返回逐条核对结果
  async confirmDraftImport() {
    const drafts = this._drafts || [];
    if (drafts.length === 0) {
      return;
    }
    const incomplete = drafts.filter((d) => courseImport.missingFields(d).length > 0);
    if (incomplete.length > 0) {
      wx.showToast({
        title: `还有 ${incomplete.length} 项缺时间/周次/星期，请先补全或移除`,
        icon: 'none',
      });
      return;
    }
    wx.showLoading({ title: '保存中', mask: true });
    try {
      const { statuses, uncertain } = await courseImport.saveDrafts(drafts, api);
      wx.hideLoading();
      await this.load(); // 刷新课表（保留真实当前周，不篡改学期）
      const created = statuses.filter((s) => s.status === 'created').length;
      const skipped = statuses.filter((s) => s.status === 'skipped').length;
      const uncertainCount = statuses.filter((s) => s.status === 'uncertain').length;
      const failed = courseImport.failedDrafts(statuses);
      if (failed.length > 0) {
        // 部分失败：只保留失败项供修正后重试，不整批重放
        this._drafts = failed;
        this.setData({
          hasPendingSlots: courseImport.pendingSlots(failed).length > 0,
          draftViews: draftViews(failed),
          warnings: [
            skipped ? `${skipped} 项被后端判为无效（可修正后重试）` : '',
            uncertainCount ? `${uncertainCount} 项结果待确认（已核对课表列表）` : '',
            uncertain ? '保存响应不明：已按课表列表核对，请确认无重复后再重试' : '',
          ].filter(Boolean),
        });
        wx.showToast({
          title: `已导入 ${created} 节，${failed.length} 项未成功`,
          icon: 'none',
          duration: 3000,
        });
        return;
      }
      this.cancelDraftImport();
      wx.showToast({ title: `已导入 ${created} 节课`, icon: 'none' });
      // 未设置学期时引导配置：周次过滤依赖学期设置
      if (this.data.needSetup) {
        wx.showModal({
          title: '设置学期',
          content: '导入完成！请先设置学期（第一周的周一与总周数），课表才能按周次过滤显示。',
          showCancel: false,
          confirmText: '知道了',
        });
      }
    } catch (err) {
      wx.hideLoading();
      wx.showToast({ title: err.message || '保存失败', icon: 'none' });
    }
  },
});
