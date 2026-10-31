// C6 验收（逻辑层）：驱动真实 utils/datetime.js 与 utils/semester.js。
// - 学期周次推算用固定样例日期（任务书验收值：开学 2026-09-07 时
//   10-25=第7周、10-26=第8周、10-30=第8周周五、10-31=第8周周六）
// - semester.js 用模拟 api 覆盖在线读取/缓存、离线推算、未配置清缓存与保存失败
// 由 tests/run-tests.js 以独立进程运行（node tests/semester-logic.test.js）。

const assert = require('assert');
const { runtime } = require('./runtime');

// runtime 用 vm 加载模块，返回值对象来自独立 realm：JSON 往返后再比较结构
function plain(value) {
  return JSON.parse(JSON.stringify(value));
}

let passed = 0;
async function check(name, fn) {
  await fn();
  passed += 1;
  console.log('PASS', name);
}

// ---------- 纯日期/周次函数 ----------
const rt = runtime();
const dt = rt.load('utils/datetime.js');

// ---------- semester.js 的模拟 api ----------
function makeApi({ semesterData, calendarBehavior, saveBehavior }) {
  return {
    getSemester: async () => {
      if (semesterData === 'throw') throw new Error('网络失败');
      return semesterData;
    },
    getCalendar: async () => {
      if (calendarBehavior === 'throw') throw new Error('网络失败');
      return calendarBehavior;
    },
    saveSemester: async (settings) => {
      if (saveBehavior === '422') {
        throw new Error('HTTP 422');
      }
      return { configured: true, settings: { id: 1, ...settings } };
    },
  };
}

async function main() {
  await check('parseDate：合法/格式错/不存在的日期', () => {
    assert.deepStrictEqual(plain(dt.parseDate('2026-09-07')), { y: 2026, m: 9, d: 7 });
    assert.strictEqual(dt.parseDate('2026-2-3'), null);
    assert.strictEqual(dt.parseDate('2026-02-30'), null);
    assert.strictEqual(dt.parseDate('abc'), null);
    assert.strictEqual(dt.parseDate(20260907), null);
  });

  await check('daysBetween：跨月/跨年/夏令时切换日的纯日历日差', () => {
    assert.strictEqual(dt.daysBetween('2026-10-01', '2026-09-30'), 1);
    assert.strictEqual(dt.daysBetween('2026-01-01', '2025-12-31'), 1);
    assert.strictEqual(dt.daysBetween('2026-03-30', '2026-03-28'), 2); // 中欧夏令时切换日
    assert.strictEqual(dt.daysBetween('2026-09-07', '2026-09-07'), 0);
    assert.ok(Number.isNaN(dt.daysBetween('x', '2026-09-07')));
  });

  await check('computeWeek：任务书固定样例（开学 2026-09-07，共 18 周）', () => {
    const start = '2026-09-07';
    assert.deepStrictEqual(plain(dt.computeWeek(start, 18, '2026-09-07')), {
      week: 1,
      status: 'in_term',
    });
    assert.deepStrictEqual(plain(dt.computeWeek(start, 18, '2026-09-13')), {
      week: 1,
      status: 'in_term',
    }); // 周日
    assert.deepStrictEqual(plain(dt.computeWeek(start, 18, '2026-09-14')), {
      week: 2,
      status: 'in_term',
    });
    assert.deepStrictEqual(plain(dt.computeWeek(start, 18, '2026-10-25')), {
      week: 7,
      status: 'in_term',
    });
    assert.deepStrictEqual(plain(dt.computeWeek(start, 18, '2026-10-26')), {
      week: 8,
      status: 'in_term',
    });
    assert.deepStrictEqual(plain(dt.computeWeek(start, 18, '2026-10-30')), {
      week: 8,
      status: 'in_term',
    });
    assert.deepStrictEqual(plain(dt.computeWeek(start, 18, '2026-10-31')), {
      week: 8,
      status: 'in_term',
    });
  });

  await check('computeWeek：开学前/最后一周/结束后不夹到边界周', () => {
    const start = '2026-09-07';
    assert.deepStrictEqual(plain(dt.computeWeek(start, 18, '2026-09-06')), {
      week: null,
      status: 'before_term',
    });
    // 18 周覆盖日差 0..125：2027-01-10 为第 18 周最后一天，01-11 起结束
    assert.deepStrictEqual(plain(dt.computeWeek(start, 18, '2027-01-10')), {
      week: 18,
      status: 'in_term',
    });
    assert.deepStrictEqual(plain(dt.computeWeek(start, 18, '2027-01-11')), {
      week: null,
      status: 'after_term',
    });
  });

  await check('computeWeek：非法输入返回 unconfigured', () => {
    assert.deepStrictEqual(plain(dt.computeWeek('bad', 18, '2026-10-30')), {
      week: null,
      status: 'unconfigured',
    });
    assert.deepStrictEqual(plain(dt.computeWeek('2026-09-07', 0, '2026-10-30')), {
      week: null,
      status: 'unconfigured',
    });
    assert.deepStrictEqual(plain(dt.computeWeek('2026-09-07', 54, '2026-10-30')), {
      week: null,
      status: 'unconfigured',
    });
    assert.deepStrictEqual(plain(dt.computeWeek('2026-09-07', 18, 'bad')), {
      week: null,
      status: 'unconfigured',
    });
  });

  await check('isMonday：仅周一通过（第一周起始日期校验）', () => {
    assert.strictEqual(dt.isMonday('2026-09-07'), true);
    assert.strictEqual(dt.isMonday('2026-09-08'), false);
    assert.strictEqual(dt.isMonday('bad'), false);
  });

  await check('weekNumberOptions：按总周数生成且钳制在 1-53', () => {
    assert.strictEqual(dt.weekNumberOptions(18).length, 18);
    assert.strictEqual(dt.weekNumberOptions(18)[0], '第1周');
    assert.strictEqual(dt.weekNumberOptions(18)[17], '第18周');
    assert.strictEqual(dt.weekNumberOptions(0).length, 1);
    assert.strictEqual(dt.weekNumberOptions(100).length, 53);
  });

  await check('localDateText：本机日历今天为 YYYY-MM-DD', () => {
    assert.match(dt.localDateText(), /^\d{4}-\d{2}-\d{2}$/);
  });

  // ---------- semester.js：在线读取与缓存 ----------
  await check('getSettings：配置存在时缓存到本地存储', async () => {
    const r = runtime({
      api: makeApi({
        semesterData: {
          configured: true,
          settings: { id: 1, start_date: '2026-09-07', total_weeks: 18, timezone: 'Asia/Shanghai' },
        },
      }),
    });
    const s = r.load('utils/semester.js');
    const result = await s.getSettings();
    assert.strictEqual(result.ok, true);
    assert.strictEqual(result.configured, true);
    assert.strictEqual(r.storage.get('semester_settings').start_date, '2026-09-07');
  });

  await check('getSettings：未配置时清除本地缓存', async () => {
    const r = runtime({
      api: makeApi({ semesterData: { configured: false, settings: null } }),
    });
    r.storage.set('semester_settings', { start_date: '2026-09-07', total_weeks: 18 });
    const s = r.load('utils/semester.js');
    const result = await s.getSettings();
    assert.strictEqual(result.configured, false);
    assert.strictEqual(r.storage.get('semester_settings'), undefined);
  });

  await check('getSettings：请求失败返回 ok:false 且不覆盖缓存', async () => {
    const r = runtime({ api: makeApi({ semesterData: 'throw' }) });
    r.storage.set('semester_settings', { start_date: '2026-09-07', total_weeks: 18 });
    const s = r.load('utils/semester.js');
    const result = await s.getSettings();
    assert.strictEqual(result.ok, false);
    assert.strictEqual(r.storage.get('semester_settings').start_date, '2026-09-07');
  });

  await check('getToday：在线结果直接透传且带 ok/offline 标记', async () => {
    const calendar = {
      date: '2026-10-30',
      day_of_week: 5,
      week: 8,
      status: 'in_term',
      timezone: 'Asia/Shanghai',
      settings: { id: 1, start_date: '2026-09-07', total_weeks: 18, timezone: 'Asia/Shanghai' },
      courses: [],
    };
    const r = runtime({ api: makeApi({ calendarBehavior: calendar }) });
    const s = r.load('utils/semester.js');
    const result = await s.getToday();
    assert.strictEqual(result.ok, true);
    assert.strictEqual(result.offline, false);
    assert.strictEqual(result.week, 8);
    assert.strictEqual(result.day_of_week, 5);
    assert.strictEqual(r.storage.get('semester_settings').start_date, '2026-09-07');
  });

  await check('getToday：断网且有缓存时离线推算并标记 offline', async () => {
    const r = runtime({
      api: makeApi({
        semesterData: 'throw',
        calendarBehavior: 'throw',
      }),
    });
    r.storage.set('semester_settings', { start_date: '2026-01-05', total_weeks: 53 });
    const s = r.load('utils/semester.js');
    const result = await s.getToday();
    assert.strictEqual(result.ok, true);
    assert.strictEqual(result.offline, true);
    assert.strictEqual(result.status, 'in_term'); // 2026-01-05 起 53 周覆盖整个 2026 年
    assert.ok(Number.isInteger(result.week) && result.week >= 1 && result.week <= 53);
    assert.deepStrictEqual(plain(result.courses), []);
    assert.match(result.date, /^\d{4}-\d{2}-\d{2}$/);
  });

  await check('getToday：断网且无缓存返回 ok:false', async () => {
    const r = runtime({
      api: makeApi({ semesterData: 'throw', calendarBehavior: 'throw' }),
    });
    const s = r.load('utils/semester.js');
    const result = await s.getToday();
    assert.strictEqual(result.ok, false);
    assert.strictEqual(result.offline, true);
  });

  await check('getToday：日历返回 unconfigured 时清除缓存', async () => {
    const r = runtime({
      api: makeApi({
        calendarBehavior: { status: 'unconfigured', week: null, settings: null, courses: [] },
      }),
    });
    r.storage.set('semester_settings', { start_date: '2026-09-07', total_weeks: 18 });
    const s = r.load('utils/semester.js');
    const result = await s.getToday();
    assert.strictEqual(result.status, 'unconfigured');
    assert.strictEqual(r.storage.get('semester_settings'), undefined);
  });

  await check('saveSettings：成功回写缓存，失败返回 ok:false 与错误', async () => {
    const ok = runtime({ api: makeApi({}) });
    const s1 = ok.load('utils/semester.js');
    const good = await s1.saveSettings({ start_date: '2026-09-07', total_weeks: 18 });
    assert.strictEqual(good.ok, true);
    assert.strictEqual(ok.storage.get('semester_settings').total_weeks, 18);

    const bad = runtime({ api: makeApi({ saveBehavior: '422' }) });
    const s2 = bad.load('utils/semester.js');
    const failed = await s2.saveSettings({ start_date: '2026-09-08', total_weeks: 18 });
    assert.strictEqual(failed.ok, false);
    assert.ok(failed.error);
    assert.strictEqual(bad.storage.get('semester_settings'), undefined);
  });

  console.log(`\n全部通过：${passed} 项`);
}

main().catch((err) => {
  console.error('FAIL:', err.message);
  process.exit(1);
});
