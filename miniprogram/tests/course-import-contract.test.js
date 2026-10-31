// C7 验收（契约/联调层）：由 scripts/check_c7_integration.py 启动真实后端（临时数据库）。
// 真实 utils/api.js + utils/course_import.js + 课表页真实逻辑：
// - parse-image 错误映射（无视觉模型 503、无鉴权 401）
// - 草稿展示 → 未补全禁止保存（确认前无课程写入）→ 节次映射补全 → 真实 bulk 落库
// - 部分失败按 index 标注，失败项修正后单独重试；响应不明先核对列表标「待确认」
// 真实视觉模型调用不在此脚本（CI 无 Key；模型端由 B7 验收，见 docs/b7-parsing.md）。

const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const { runtime } = require('./runtime');

const baseUrl = 'http://127.0.0.1:' + process.env.C7_TEST_PORT;
const token = process.env.API_TOKEN;
if (!process.env.C7_TEST_PORT) {
  throw new Error('请运行 python scripts/check_c7_integration.py');
}

// 1x1 PNG fixture（本地生成，稳定来源；真实课表 fixture 见 tests_fixtures/b7/schedule.png）
const FIXTURE = path.join(__dirname, 'tmp-c7-upload.png');
fs.writeFileSync(
  FIXTURE,
  Buffer.from(
    'iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg==',
    'base64'
  )
);
process.on('exit', () => fs.rmSync(FIXTURE, { force: true }));

const toasts = [];
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
    uploadFile: (options) => {
      const body = new FormData();
      body.append(
        options.name || 'image',
        new Blob([fs.readFileSync(options.filePath)]),
        'image.png'
      );
      Object.entries(options.formData || {}).forEach(([key, value]) => body.append(key, value));
      fetch(options.url, { method: 'POST', headers: options.header, body })
        .then(async (response) => {
          const text = await response.text();
          options.success({ statusCode: response.status, data: text });
        })
        .catch((error) => options.fail({ errMsg: error.message }));
      return { abort() {} };
    },
    showToast: (opts) => toasts.push(opts.title),
    showLoading: () => {},
    hideLoading: () => {},
    showModal: () => {},
    previewImage: () => {},
  },
});
const api = rt.load('utils/api.js');
const ci = rt.load('utils/course_import.js');

let passed = 0;
async function check(name, fn) {
  await fn();
  passed += 1;
  console.log('PASS ' + name);
}

const COMPLETE = {
  name: '高等数学',
  day_of_week: 1,
  start_time: '08:00',
  end_time: '09:40',
  location: '教三 301',
  teacher: '张老师',
  weeks: [1, 3, 5],
};

async function cleanupNames(names) {
  for (const course of await api.getCourses()) {
    if (names.includes(course.name)) {
      await api.deleteCourse(course.id);
    }
  }
}

async function main() {
  await check('真实 parse-image：未配置视觉模型返回 503 且错误可读', async () => {
    const err = await api.parseCourseImage(FIXTURE).then(
      () => null,
      (e) => e
    );
    assert.ok(err, '应失败');
    assert.equal(err.statusCode, 503);
    assert.match(err.message, /视觉模型/);
  });

  await check('真实 parse-image：无鉴权返回 401', async () => {
    const response = await fetch(baseUrl + '/api/courses/parse-image', { method: 'POST' });
    assert.equal(response.status, 401);
  });

  await check('课表页真实流程：未补全禁止保存，节次映射补全后落库', async () => {
    const page = rt.loadPage('pages/schedule/schedule.js');
    await page.load(); // 真实后端：学期/课程列表
    const before = (await api.getCourses()).length;
    await page.showDrafts({
      courses: [COMPLETE],
      pending_courses: [
        {
          name: '大学物理',
          day_of_week: 2,
          start_time: null,
          end_time: null,
          slot: '1-2',
          weeks: [1, 2],
          needs_confirmation: ['time'],
        },
      ],
      warnings: ['第2项需要确认'],
      skipped: 0,
    });
    assert.equal(page.data.draftViews.length, 2);
    assert.equal(page.data.hasPendingSlots, true);
    assert.equal(page.data.draftViews[1].needsText, '缺时间');
    // 未补全：确认导入被阻止，数据库不变
    await page.confirmDraftImport();
    assert.equal((await api.getCourses()).length, before, '确认前不得写入课程');
    assert.ok(toasts.some((t) => /补全/.test(t)));
    // 配置节次时间并应用映射
    page.openSlotModal();
    assert.deepEqual(JSON.parse(JSON.stringify(page.data.slotList)), ['1-2']);
    page.setData({ slotForms: [{ slot: '1-2', start: '08:00', end: '09:40' }] });
    page.saveSlotMapping();
    assert.equal(page.data.importStage, 'draft');
    assert.equal(page.data.hasPendingSlots, false);
    // 全部补全 → 真实保存落库
    await page.confirmDraftImport();
    const names = (await api.getCourses()).map((c) => c.name);
    assert.ok(names.includes('高等数学') && names.includes('大学物理'));
    await cleanupNames(['高等数学', '大学物理']);
  });

  await check('真实保存部分失败：skipped 按 index 标注，修正后只重试失败项', async () => {
    const drafts = [
      COMPLETE,
      { ...COMPLETE, name: '坏周次课', weeks: 'not-a-list' },
      { ...COMPLETE, name: '好课2' },
    ];
    const { statuses } = await ci.saveDrafts(drafts, api);
    assert.deepEqual(
      statuses.map((s) => [s.draft.name, s.status]),
      [
        ['高等数学', 'created'],
        ['坏周次课', 'skipped'],
        ['好课2', 'created'],
      ]
    );
    assert.ok(statuses[1].reason);
    // 只恢复失败项（修正周次后重试），不整批重放
    const fixed = ci.failedDrafts(statuses).map((d) => ({ ...d, weeks: [1, 2] }));
    const retry = await ci.saveDrafts(fixed, api);
    assert.equal(retry.statuses[0].status, 'created');
    const names = (await api.getCourses()).map((c) => c.name);
    assert.ok(names.includes('坏周次课'));
    await cleanupNames(['高等数学', '好课2', '坏周次课']);
  });

  await check('响应不明：先核对列表，已存在的标成功、其余标待确认，不自动重放', async () => {
    const created = await api.createCourse({
      name: '已存在课',
      day_of_week: 1,
      start_time: '08:00',
      end_time: '09:40',
      location: '',
      teacher: '',
      weeks: [],
    });
    const flaky = {
      bulkCreateCourses: async () => {
        throw new Error('网络失败');
      },
      getCourses: () => api.getCourses(),
    };
    const { statuses, uncertain } = await ci.saveDrafts(
      [
        { ...COMPLETE, name: '已存在课' },
        { ...COMPLETE, name: '不确定课' },
      ],
      flaky
    );
    assert.equal(uncertain, true);
    assert.deepEqual(
      statuses.map((s) => [s.draft.name, s.status]),
      [
        ['已存在课', 'created'],
        ['不确定课', 'uncertain'],
      ]
    );
    await api.deleteCourse(created.id);
  });

  console.log(`\n全部通过：${passed} 项`);
}

main().catch((err) => {
  console.error('FAIL:', err.message);
  process.exit(1);
});
