// 课表图片导入的纯逻辑（B7 契约见 docs/b7-parsing.md）：
// - parse-image 返回 courses（时间完整）+ pending_courses（需确认草稿）+ warnings + skipped
// - 草稿核对名称/星期/地点/教师/周次；图中无具体时间时按标准节次时间预填（可见可改，
//   也可在「配置节次时间」里统一调整），无节次标签的条目需手填
// - 用户确认后才送 bulk 落库；按实际返回区分成功/无效/明确失败/结果不明，失败项单独恢复
// 本模块不操作 UI 与数据库，供页面与测试复用。

function validClock(value) {
  return typeof value === 'string' && /^(?:[01][0-9]|2[0-3]):[0-5][0-9]$/.test(value);
}

// 标准节次时间（按用户作息约定）：第 1 节 08:00-09:40、第 2 节 10:00-11:40、
// 第 3 节 13:00-14:40、第 4 节 16:00-17:40、第 5 节 19:00-20:40。
// 图中没有具体时间时用此表预填草稿，用户可在草稿或节次映射中修改，不静默套用。
const DEFAULT_SLOT_TIMES = [
  { start: '08:00', end: '09:40' },
  { start: '10:00', end: '11:40' },
  { start: '13:00', end: '14:40' },
  { start: '16:00', end: '17:40' },
  { start: '19:00', end: '20:40' },
];

/**
 * 从节次标签推断节次序号：支持「第N行」直接取 N；「a-b」/数字按 ceil(首数/2)
 * （如 1-2→1、3-4→2、9-10→5）；无法识别返回 null。
 */
function slotBlockIndex(slot) {
  if (!slot) {
    return null;
  }
  const text = String(slot);
  const row = text.match(/第\s*(\d+)\s*行/);
  if (row) {
    return Number(row[1]);
  }
  const range = text.match(/^(\d+)\s*-\s*(\d+)$/);
  if (range) {
    return Math.ceil(Number(range[1]) / 2);
  }
  const single = text.match(/\d+/);
  return single ? Math.ceil(Number(single[0]) / 2) : null;
}

/** 按节次序号取标准时间；序号超表或无标签返回 null。 */
function defaultSlotTime(slot) {
  const index = slotBlockIndex(slot);
  if (!index || index < 1 || index > DEFAULT_SLOT_TIMES.length) {
    return null;
  }
  return DEFAULT_SLOT_TIMES[index - 1];
}

/** 识别结果合并为统一草稿列表：缺时间的条目按节次标签预填标准时间（可见可改）。 */
function mergeDrafts(result) {
  const ready = (result.courses || []).map((c) => ({ ...c, needs_confirmation: [] }));
  const pending = (result.pending_courses || []).map((c) => {
    let draft = { ...c, needs_confirmation: c.needs_confirmation || [] };
    if (!validClock(draft.start_time) || !validClock(draft.end_time)) {
      const defaultTime = defaultSlotTime(draft.slot);
      if (defaultTime) {
        draft = {
          ...draft,
          start_time: defaultTime.start,
          end_time: defaultTime.end,
          needs_confirmation: draft.needs_confirmation.filter((n) => n !== 'time'),
        };
      }
    }
    return draft;
  });
  return ready.concat(pending);
}

/** 草稿缺哪些必填项（needs 取值 time/weeks/day_of_week；weeks=null 表示需确认）。 */
function missingFields(draft) {
  const needs = [];
  if (
    !validClock(draft.start_time) ||
    !validClock(draft.end_time) ||
    !(draft.start_time < draft.end_time)
  ) {
    needs.push('time');
  }
  if (draft.weeks == null) {
    needs.push('weeks');
  }
  if (!Number.isInteger(draft.day_of_week) || draft.day_of_week < 1 || draft.day_of_week > 7) {
    needs.push('day_of_week');
  }
  return needs;
}

/** 收集缺时间且带节次标签的草稿用到的不同 slot（供一次性配置节次时间）。 */
function pendingSlots(drafts) {
  const slots = new Set();
  drafts.forEach((draft) => {
    if (draft.slot && missingFields(draft).includes('time')) {
      slots.add(draft.slot);
    }
  });
  return Array.from(slots);
}

/** 用节次→时间映射填充草稿时间；无 slot 或 slot 未映射的条目保持原样（仍需手填）。 */
function applySlotMapping(drafts, mapping) {
  return drafts.map((draft) => {
    if (draft.start_time && draft.end_time) {
      return draft;
    }
    const slot = mapping[draft.slot];
    if (
      draft.slot &&
      slot &&
      validClock(slot.start) &&
      validClock(slot.end) &&
      slot.start < slot.end
    ) {
      return { ...draft, start_time: slot.start, end_time: slot.end };
    }
    return draft;
  });
}

/** 草稿转 bulk 提交条目：去掉 needs_confirmation/slot 等识别专用字段。 */
function toBulkItem(draft) {
  return {
    name: String(draft.name || '').trim(),
    day_of_week: draft.day_of_week,
    start_time: draft.start_time,
    end_time: draft.end_time,
    location: draft.location || '',
    teacher: draft.teacher || '',
    weeks: draft.weeks,
  };
}

/** 按 bulk 返回（created 按序、skipped 带 index/reason）为每条草稿标注保存结果。 */
function buildStatuses(drafts, result) {
  const skippedIndexes = new Map((result.skipped || []).map((s) => [s.index, s.reason]));
  const createdList = result.created || [];
  let createdCursor = 0;
  return drafts.map((draft, index) => {
    if (skippedIndexes.has(index)) {
      return { draft, status: 'skipped', reason: skippedIndexes.get(index) };
    }
    const course = createdList[createdCursor];
    createdCursor += 1;
    return { draft, status: 'created', course };
  });
}

/**
 * 提交草稿落库。成功返回 { statuses, uncertain: false }；
 * 网络失败等响应不明时先按列表核对（同名课程不保证去重，无法确认的标「待确认」），
 * 不自动整批重放。statuses 每条为 { draft, status: created/skipped/uncertain, reason?, course? }。
 */
async function saveDrafts(drafts, api) {
  let result;
  try {
    result = await api.bulkCreateCourses(drafts.map(toBulkItem));
  } catch (err) {
    return verifyByList(drafts, api);
  }
  return { statuses: buildStatuses(drafts, result), uncertain: false };
}

/** 响应不明时用课程列表核对；同名同星期同时段视为同一条（仅提示用，不保证去重）。 */
async function verifyByList(drafts, api) {
  let courses = [];
  try {
    courses = await api.getCourses();
  } catch (err) {
    /* 仍不可达：全部标待确认 */
  }
  const keys = new Set(
    courses.map((c) => [c.name, c.day_of_week, c.start_time, c.end_time].join('|'))
  );
  return {
    statuses: drafts.map((draft) => {
      const key = [
        toBulkItem(draft).name,
        draft.day_of_week,
        draft.start_time,
        draft.end_time,
      ].join('|');
      if (keys.has(key)) {
        return { draft, status: 'created' };
      }
      return { draft, status: 'uncertain', reason: '结果待确认' };
    }),
    uncertain: true,
  };
}

/** 从状态列表筛出未成功保存的草稿（跳过项可修正后与待确认项一起重试）。 */
function failedDrafts(statuses) {
  return statuses.filter((s) => s.status !== 'created').map((s) => s.draft);
}

module.exports = {
  mergeDrafts,
  missingFields,
  pendingSlots,
  applySlotMapping,
  toBulkItem,
  buildStatuses,
  saveDrafts,
  failedDrafts,
  defaultSlotTime,
};
