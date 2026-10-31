// C6 验收（契约/联调层）：由 scripts/check_c6_integration.py 启动真实后端，
// 这里用真实 utils/api.js 与 utils/semester.js 驱动，临时数据库，不做自建成功 Mock。
// 固定样例日期：开学 2026-09-07 时 10-25=第7周、10-26=第8周、10-30=第8周周五、10-31=第8周周六。

const assert = require('node:assert/strict');
const { runtime } = require('./runtime');

const baseUrl = 'http://127.0.0.1:' + process.env.C6_TEST_PORT;
const token = process.env.API_TOKEN;
if (!process.env.C6_TEST_PORT) {
  throw new Error('请运行 python scripts/check_c6_integration.py');
}

const rt = runtime({
  config: { baseUrl, apiKey: token },
  wx: {
    request: (options) => {
      fetch(options.url, {
        method: options.method,
        headers: options.header,
        body: options.data ? JSON.stringify(options.data) : undefined,
      })
        .then(async (response) => {
          const text = await response.text();
          options.success({ statusCode: response.status, data: text ? JSON.parse(text) : null });
        })
        .catch((error) => options.fail({ errMsg: error.message }));
    },
  },
});
const api = rt.load('utils/api.js');
const semester = rt.load('utils/semester.js');

let passed = 0;
async function check(name, fn) {
  await fn();
  passed += 1;
  console.log('PASS ' + name);
}

async function raw(path, method = 'GET', body) {
  const response = await fetch(baseUrl + path, {
    method,
    headers: { 'X-API-Key': token, 'Content-Type': 'application/json' },
    body: body ? JSON.stringify(body) : undefined,
  });
  const text = await response.text();
  return { status: response.status, data: text ? JSON.parse(text) : null };
}

const SETTINGS = { start_date: '2026-09-07', total_weeks: 18 };

async function main() {
  await check('未配置：semester 与 calendar 的契约形态', async () => {
    const s = await raw('/api/semester');
    assert.equal(s.status, 200);
    assert.equal(s.data.configured, false);
    assert.equal(s.data.settings, null);
    const c = await raw('/api/calendar');
    assert.equal(c.status, 200);
    assert.equal(c.data.status, 'unconfigured');
    assert.equal(c.data.week, null);
    assert.deepEqual(c.data.courses, []);
    assert.match(c.data.date, /^\d{4}-\d{2}-\d{2}$/);
    assert.ok([1, 2, 3, 4, 5, 6, 7].includes(c.data.day_of_week));
  });

  await check('未认证请求返回 401', async () => {
    const response = await fetch(baseUrl + '/api/semester');
    assert.equal(response.status, 401);
  });

  await check('PUT 整体保存并读回（settings.id=1）', async () => {
    const put = await raw('/api/semester', 'PUT', SETTINGS);
    assert.equal(put.status, 200);
    assert.equal(put.data.configured, true);
    assert.equal(put.data.settings.id, 1);
    assert.equal(put.data.settings.start_date, '2026-09-07');
    assert.equal(put.data.settings.total_weeks, 18);
    const get = await raw('/api/semester');
    assert.deepEqual(get.data.settings, put.data.settings);
  });

  await check('非法设置 422 且不覆盖原配置（非周一/超范围/未知字段）', async () => {
    assert.equal(
      (await raw('/api/semester', 'PUT', { ...SETTINGS, start_date: '2026-09-08' })).status,
      422
    );
    assert.equal((await raw('/api/semester', 'PUT', { ...SETTINGS, total_weeks: 0 })).status, 422);
    assert.equal((await raw('/api/semester', 'PUT', { ...SETTINGS, total_weeks: 54 })).status, 422);
    assert.equal((await raw('/api/semester', 'PUT', { ...SETTINGS, extra: 'x' })).status, 422);
    const get = await raw('/api/semester');
    assert.equal(get.data.settings.start_date, '2026-09-07');
    assert.equal(get.data.settings.total_weeks, 18);
  });

  await check(
    '任务书固定样例：10-25=第7周、10-26=第8周、10-30=第8周周五、10-31=第8周周六',
    async () => {
      const cases = [
        ['2026-10-25', 7, 7],
        ['2026-10-26', 8, 1],
        ['2026-10-30', 8, 5],
        ['2026-10-31', 8, 6],
      ];
      for (const [date, week, dow] of cases) {
        const c = await raw('/api/calendar?date=' + date);
        assert.equal(c.status, 200, date);
        assert.equal(c.data.date, date);
        assert.equal(c.data.week, week, date);
        assert.equal(c.data.day_of_week, dow, date);
        assert.equal(c.data.status, 'in_term', date);
      }
    }
  );

  await check('学期边界：开学前/最后一周/结束后 week=null 且 courses 为空', async () => {
    const before = await raw('/api/calendar?date=2026-09-06');
    assert.equal(before.data.status, 'before_term');
    assert.equal(before.data.week, null);
    const last = await raw('/api/calendar?date=2027-01-10');
    assert.equal(last.data.status, 'in_term');
    assert.equal(last.data.week, 18);
    const after = await raw('/api/calendar?date=2027-01-11');
    assert.equal(after.data.status, 'after_term');
    assert.equal(after.data.week, null);
    assert.deepEqual(after.data.courses, []);
  });

  await check('课程按星期与周次过滤（单双周/空weeks/无课日）', async () => {
    // 周三 1,8 周（离散）与 2,4,6 周（双周）；周一每周
    const a = await api.createCourse({
      name: '离散周课程',
      day_of_week: 3,
      start_time: '08:00',
      end_time: '09:40',
      location: '',
      teacher: '',
      weeks: [1, 8],
    });
    const b = await api.createCourse({
      name: '双周课程',
      day_of_week: 3,
      start_time: '10:00',
      end_time: '11:40',
      location: '',
      teacher: '',
      weeks: [2, 4, 6],
    });
    const c = await api.createCourse({
      name: '每周课程',
      day_of_week: 1,
      start_time: '14:00',
      end_time: '15:40',
      location: '',
      teacher: '',
      weeks: [],
    });
    // 2026-10-28 周三第8周：只有离散周课程
    const w8 = await raw('/api/calendar?date=2026-10-28');
    assert.equal(w8.data.week, 8);
    assert.deepEqual(
      w8.data.courses.map((x) => x.name),
      ['离散周课程']
    );
    // 2026-10-14 周三第6周：只有双周课程
    const w6 = await raw('/api/calendar?date=2026-10-14');
    assert.deepEqual(
      w6.data.courses.map((x) => x.name),
      ['双周课程']
    );
    // 2026-10-26 周一第8周：只有每周课程（空 weeks 全周有效）
    const mon = await raw('/api/calendar?date=2026-10-26');
    assert.deepEqual(
      mon.data.courses.map((x) => x.name),
      ['每周课程']
    );
    // 2026-10-31 周六：无课日
    const sat = await raw('/api/calendar?date=2026-10-31');
    assert.deepEqual(sat.data.courses, []);
    await api.deleteCourse(a.id);
    await api.deleteCourse(b.id);
    await api.deleteCourse(c.id);
  });

  await check('semester.js 适配层：getSettings/saveSettings/getToday 走真实后端', async () => {
    const result = await semester.getSettings();
    assert.equal(result.ok, true);
    assert.equal(result.configured, true);
    assert.equal(result.settings.start_date, '2026-09-07');
    const saved = await semester.saveSettings({ start_date: '2026-09-07', total_weeks: 20 });
    assert.equal(saved.ok, true);
    assert.equal(saved.settings.total_weeks, 20);
    const today = await semester.getToday();
    assert.equal(today.ok, true);
    assert.equal(today.offline, false);
    assert.equal(today.status, 'in_term');
    assert.ok(Number.isInteger(today.week) && today.week >= 1 && today.week <= 20);
    // 恢复 18 周，避免影响后续样例
    await semester.saveSettings(SETTINGS);
  });

  await check('今日页真实加载：真实周次标签与当天课程来自 B6 日历', async () => {
    const page = rt.loadPage('pages/index/index.js');
    await page.loadToday();
    const cal = await raw('/api/calendar');
    assert.match(page.data.todayLabel, /^第\d+周 · 周[一二三四五六日] · \d{4}-\d{2}-\d{2}$/);
    assert.equal(page.data.todayLabel.startsWith('第' + cal.data.week + '周'), true);
    assert.equal(page.data.needSetup, false);
    // 建一门服务器今天的课程 → 应出现在页面课程列表
    const course = await api.createCourse({
      name: '今日页课程',
      day_of_week: cal.data.day_of_week,
      start_time: '08:00',
      end_time: '09:40',
      location: '',
      teacher: '',
      weeks: [cal.data.week],
    });
    await page.loadToday();
    assert.ok(page.data.courses.some((c) => c.name === '今日页课程'));
    await api.deleteCourse(course.id);
  });

  await check('课表页真实加载：浏览周与真实周一致、周视图来自课程列表分组', async () => {
    const page = rt.loadPage('pages/schedule/schedule.js');
    await page.load();
    const cal = await raw('/api/calendar');
    assert.equal(page.data.realWeek, cal.data.week);
    assert.equal(page.data.browseWeek, cal.data.week);
    assert.equal(page.data.isBrowsing, false);
    // 周视图是课程列表按星期分组（不是把单日日历当整周）
    const course = await api.createCourse({
      name: '分组课程',
      day_of_week: 1,
      start_time: '08:00',
      end_time: '09:40',
      location: '',
      teacher: '',
      weeks: [],
    });
    await page.load();
    const monday = page.data.weekDays.find((d) => d.day === 1);
    assert.ok(monday.courses.some((c) => c.name === '分组课程'));
    // 浏览其他周只是切换高亮，不改学期配置
    page.setData({ browseWeek: cal.data.week === 1 ? 2 : 1, isBrowsing: true });
    page.applyCourses();
    assert.equal((await raw('/api/semester')).data.settings.start_date, '2026-09-07');
    await api.deleteCourse(course.id);
    await page.load();
  });

  await check('api.js 封装：getCalendar(date) 与无参数查询服务器今天', async () => {
    const fixed = await api.getCalendar('2026-10-30');
    assert.equal(fixed.week, 8);
    assert.equal(fixed.day_of_week, 5);
    const today = await api.getCalendar();
    assert.match(today.date, /^\d{4}-\d{2}-\d{2}$/);
    assert.equal(today.status, 'in_term');
  });

  console.log(`\n全部通过：${passed} 项`);
}

main().catch((err) => {
  console.error('FAIL:', err.message);
  process.exit(1);
});
