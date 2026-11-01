// 一句话日程的纯逻辑（C8，B7 契约见 docs/b7-parsing.md 第二节）：
// - POST /api/tasks/parse-text 返回可确认草稿（source/title/note/due_at/remind_at/needs_confirmation）
// - 缺失/歧义/过去时间只标记待确认，不自动修正；明确截止日期不自动生成提醒
// - 确认后仅调 POST /api/tasks（后端原子创建 PC 提醒，客户端不额外建提醒）；
//   逐项保存并核对结果，失败项保留可重试，响应不明先按列表核对、不自动重放
// 本模块不操作 UI，供页面与测试复用。

// 解析参考时刻：本机当前时间（带偏移，契约要求 reference_at 必须带偏移）+ 明确时区。
// 客户端不提供 IANA 时区选择，固定 Asia/Shanghai 与 reminderOffsetMinutes 的偏移一致。
function buildReference() {
  const now = new Date();
  const pad = (v) => String(v).padStart(2, '0');
  const offsetMinutes = -now.getTimezoneOffset();
  const sign = offsetMinutes < 0 ? '-' : '+';
  const offset =
    sign + pad(Math.floor(Math.abs(offsetMinutes) / 60)) + ':' + pad(Math.abs(offsetMinutes) % 60);
  const local =
    now.getFullYear() +
    '-' +
    pad(now.getMonth() + 1) +
    '-' +
    pad(now.getDate()) +
    'T' +
    pad(now.getHours()) +
    ':' +
    pad(now.getMinutes()) +
    ':' +
    pad(now.getSeconds());
  return { reference_at: local + offset, timezone: 'Asia/Shanghai' };
}

const NEEDS_TEXT = {
  date: '日期不明',
  time: '时刻不明',
  remind_at: '提醒时刻不明',
  past: '时间已过去',
};

/** 草稿缺项标记的中文提示（needs_confirmation 取值 date/time/remind_at/past）。 */
function needsText(draft) {
  return (draft.needs_confirmation || []).map((n) => NEEDS_TEXT[n] || n).join('、');
}

/** 草稿转 POST /api/tasks 载荷：只带 title/note/due_at/remind_at 四个字段。 */
function toTaskPayload(draft) {
  return {
    title: String(draft.title || '').trim(),
    note: String(draft.note || '').trim(),
    due_at: draft.due_at || null,
    remind_at: draft.remind_at || null,
  };
}

/** 逐项核对：POST /api/tasks 成功=created、4xx=明确失败；网络失败先按列表核对。 */
async function saveDrafts(drafts, api) {
  const statuses = [];
  let uncertain = false;
  for (const draft of drafts) {
    try {
      const task = await api.createTask(toTaskPayload(draft));
      statuses.push({ draft, status: 'created', task });
    } catch (err) {
      if (err && err.statusCode && err.statusCode >= 400 && err.statusCode < 500) {
        statuses.push({ draft, status: 'failed', reason: err.message });
      } else {
        // 响应不明：不自动重放，交由列表核对
        statuses.push({ draft, status: 'uncertain', reason: err.message || '网络失败' });
        uncertain = true;
      }
    }
  }
  if (uncertain) {
    await verifyUncertain(statuses, api);
  }
  return { statuses, uncertain };
}

/** 响应不明的条目按列表核对：标题+截止+提醒完全一致视为已创建，其余保持待确认。 */
async function verifyUncertain(statuses, api) {
  let tasks = [];
  try {
    tasks = await api.getTasks();
  } catch (err) {
    return; // 仍不可达：全部保持待确认
  }
  const keys = new Set(tasks.map((t) => [t.title, t.due_at || '', t.remind_at || ''].join('|')));
  statuses.forEach((s) => {
    if (s.status !== 'uncertain') {
      return;
    }
    const payload = toTaskPayload(s.draft);
    const key = [payload.title, payload.due_at || '', payload.remind_at || ''].join('|');
    if (keys.has(key)) {
      s.status = 'created';
    }
  });
}

/** 未成功保存的草稿（失败与待确认项保留，供修正后重试）。 */
function failedDrafts(statuses) {
  return statuses.filter((s) => s.status !== 'created').map((s) => s.draft);
}

module.exports = {
  buildReference,
  needsText,
  toTaskPayload,
  saveDrafts,
  failedDrafts,
};
