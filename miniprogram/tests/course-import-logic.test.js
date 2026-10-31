// C7 验收（逻辑层）：驱动真实 utils/course_import.js 与 utils/api.js 的 uploadWithTask。
// - 草稿合并/缺项判定/节次映射/批量保存结果核对（B7 契约见 docs/b7-parsing.md）
// - 上传任务中止：abort 后 done 以 cancelled 拒绝，迟到回调不再结算；超时映射 timeout 标记
// 由 tests/run-tests.js 以独立进程运行（node tests/course-import-logic.test.js）。

const assert = require('assert');
const { runtime } = require('./runtime');

let passed = 0;
async function check(name, fn) {
  await fn();
  passed += 1;
  console.log('PASS', name);
}

function plain(value) {
  return JSON.parse(JSON.stringify(value));
}

const rt = runtime();
const ci = rt.load('utils/course_import.js');

const COMPLETE = {
  name: '高等数学',
  day_of_week: 1,
  start_time: '08:00',
  end_time: '09:40',
  location: '教三 301',
  teacher: '张老师',
  weeks: [1, 3, 5],
};

async function main() {
  await check('mergeDrafts：courses 与 pending_courses 合并并补齐 needs 标记', () => {
    const result = {
      courses: [COMPLETE],
      pending_courses: [
        {
          name: '物理',
          day_of_week: 2,
          start_time: null,
          end_time: null,
          slot: '3-4',
          weeks: [1, 2],
          needs_confirmation: ['time'],
        },
      ],
      warnings: ['第2项需要确认'],
      skipped: 0,
    };
    const drafts = ci.mergeDrafts(result);
    assert.strictEqual(drafts.length, 2);
    assert.deepStrictEqual(plain(drafts[0].needs_confirmation), []);
    assert.deepStrictEqual(plain(drafts[1].needs_confirmation), ['time']);
  });

  await check('missingFields：完整草稿无缺项，缺时间/周次/星期分别判定', () => {
    assert.deepStrictEqual(plain(ci.missingFields(COMPLETE)), []);
    assert.deepStrictEqual(
      plain(ci.missingFields({ ...COMPLETE, start_time: null, end_time: null })),
      ['time']
    );
    assert.deepStrictEqual(
      plain(ci.missingFields({ ...COMPLETE, start_time: '09:40', end_time: '08:00' })),
      ['time']
    );
    assert.deepStrictEqual(plain(ci.missingFields({ ...COMPLETE, weeks: null })), ['weeks']);
    assert.deepStrictEqual(plain(ci.missingFields({ ...COMPLETE, day_of_week: null })), [
      'day_of_week',
    ]);
    assert.deepStrictEqual(plain(ci.missingFields({ ...COMPLETE, day_of_week: 8 })), [
      'day_of_week',
    ]);
  });

  await check('pendingSlots：只收集缺时间且带节次标签的不同节次', () => {
    const drafts = [
      COMPLETE, // 完整，不参与
      { ...COMPLETE, start_time: null, end_time: null, slot: '1-2' },
      { ...COMPLETE, start_time: null, end_time: null, slot: '1-2' }, // 重复节次去重
      { ...COMPLETE, start_time: null, end_time: null, slot: '第3行' },
      { ...COMPLETE, start_time: null, end_time: null, slot: null }, // 无标签，需手填
    ];
    assert.deepStrictEqual(plain(ci.pendingSlots(drafts)), ['1-2', '第3行']);
  });

  await check('applySlotMapping：按节次映射填充时间，无标签/非法映射保持待补', () => {
    const drafts = [
      { ...COMPLETE, start_time: null, end_time: null, slot: '1-2' },
      { ...COMPLETE, start_time: null, end_time: null, slot: null },
      { ...COMPLETE, start_time: null, end_time: null, slot: '9-10' },
      COMPLETE,
    ];
    const mapped = ci.applySlotMapping(drafts, {
      '1-2': { start: '08:00', end: '09:40' },
      '9-10': { start: '19:00', end: '18:00' }, // 非法：开始晚于结束，不应用
    });
    assert.strictEqual(mapped[0].start_time, '08:00');
    assert.strictEqual(mapped[0].end_time, '09:40');
    assert.strictEqual(mapped[1].start_time, null); // 无节次标签：仍需手填
    assert.strictEqual(mapped[2].start_time, null); // 映射非法：不静默套用
    assert.strictEqual(mapped[3].start_time, '08:00'); // 原值不动
  });

  await check('toBulkItem：剥离识别专用字段并兜底空字符串', () => {
    assert.deepStrictEqual(
      plain(
        ci.toBulkItem({
          ...COMPLETE,
          slot: '1-2',
          needs_confirmation: ['time'],
          location: null,
          teacher: null,
        })
      ),
      {
        name: '高等数学',
        day_of_week: 1,
        start_time: '08:00',
        end_time: '09:40',
        location: '',
        teacher: '',
        weeks: [1, 3, 5],
      }
    );
  });

  await check('buildStatuses：created 按序对应，skipped 按 index 标注原因', () => {
    const drafts = [COMPLETE, { ...COMPLETE, name: '坏课' }, { ...COMPLETE, name: '好课2' }];
    const statuses = ci.buildStatuses(drafts, {
      created: [
        { id: 1, name: '高等数学' },
        { id: 2, name: '好课2' },
      ],
      skipped: [{ index: 1, reason: '字段无效', item: {} }],
    });
    assert.deepStrictEqual(
      plain(statuses.map((s) => [s.status, s.course && s.course.id, s.reason || null])),
      [
        ['created', 1, null],
        ['skipped', null, '字段无效'],
        ['created', 2, null],
      ]
    );
  });

  await check('saveDrafts：成功路径逐条标注，失败项可筛出单独重试', async () => {
    const api = {
      bulkCreateCourses: async (items) => {
        assert.strictEqual(items.length, 3);
        return {
          created: [{ id: 1 }, { id: 2 }],
          skipped: [{ index: 1, reason: '字段无效', item: items[1] }],
        };
      },
    };
    const drafts = [COMPLETE, { ...COMPLETE, name: '坏课' }, { ...COMPLETE, name: '好课2' }];
    const { statuses, uncertain } = await ci.saveDrafts(drafts, api);
    assert.strictEqual(uncertain, false);
    assert.deepStrictEqual(plain(ci.failedDrafts(statuses).map((d) => d.name)), ['坏课']);
  });

  await check('saveDrafts：响应不明时先核对列表，同名同时段算已存在，其余标待确认', async () => {
    const existing = [
      { id: 9, name: '已存在课', day_of_week: 1, start_time: '08:00', end_time: '09:40' },
    ];
    const api = {
      bulkCreateCourses: async () => {
        throw new Error('网络失败');
      },
      getCourses: async () => existing,
    };
    const drafts = [COMPLETE, { ...COMPLETE, name: '已存在课' }, { ...COMPLETE, name: '不确定课' }];
    const { statuses, uncertain } = await ci.saveDrafts(drafts, api);
    assert.strictEqual(uncertain, true);
    assert.deepStrictEqual(plain(statuses.map((s) => [s.draft.name, s.status])), [
      ['高等数学', 'uncertain'],
      ['已存在课', 'created'],
      ['不确定课', 'uncertain'],
    ]);
  });

  await check('saveDrafts：核对列表也失败时全部标待确认，不自动重放', async () => {
    const api = {
      bulkCreateCourses: async () => {
        throw new Error('网络失败');
      },
      getCourses: async () => {
        throw new Error('仍不可达');
      },
    };
    const { statuses, uncertain } = await ci.saveDrafts([COMPLETE], api);
    assert.strictEqual(uncertain, true);
    assert.strictEqual(statuses[0].status, 'uncertain');
  });

  // ---------- uploadWithTask：中止与迟到响应 ----------
  await check('uploadWithTask：abort 后 done 以 cancelled 拒绝，迟到成功不再结算', async () => {
    const uploads = [];
    const apiRt = runtime({
      config: { baseUrl: 'http://127.0.0.1:8001', ['api' + 'Key']: 'test-token' },
      wx: {
        uploadFile(options) {
          const task = {
            options,
            aborted: false,
            abort() {
              this.aborted = true;
              if (options.fail) {
                options.fail({ errMsg: 'uploadFile:fail abort' });
              }
            },
          };
          uploads.push(task);
          return task;
        },
      },
    });
    const realApi = apiRt.load('utils/api.js');
    const handle = realApi.uploadWithTask('/api/courses/parse-image', { filePath: 'x.png' });
    assert.strictEqual(uploads[0].options.timeout, 70000);
    const rejected = [];
    handle.done.catch((err) => rejected.push(err));
    handle.abort();
    await new Promise((r) => setTimeout(r, 10));
    assert.strictEqual(rejected.length, 1);
    assert.strictEqual(rejected[0].cancelled, true);
    // 迟到的成功回调不再结算（settled 已置位）
    uploads[0].options.success({ statusCode: 200, data: '{"courses":[]}' });
    await new Promise((r) => setTimeout(r, 10));
    assert.strictEqual(rejected.length, 1);
  });

  await check('uploadWithTask：超时 errMsg 映射 timeout 标记与中文提示', async () => {
    const apiRt = runtime({
      config: { baseUrl: 'http://127.0.0.1:8001', ['api' + 'Key']: 'test-token' },
      wx: {
        uploadFile(options) {
          setTimeout(() => options.fail({ errMsg: 'uploadFile:fail timeout' }), 0);
          return { abort() {} };
        },
      },
    });
    const realApi = apiRt.load('utils/api.js');
    const err = await realApi
      .uploadWithTask('/api/courses/parse-image', { filePath: 'x.png' })
      .done.then(
        () => null,
        (e) => e
      );
    assert.ok(err);
    assert.strictEqual(err.timeout, true);
    assert.match(err.message, /识别超时/);
  });

  await check('uploadWithTask：非 2xx 解析 detail 对象与字符串', async () => {
    const apiRt = runtime({
      config: { baseUrl: 'http://127.0.0.1:8001', ['api' + 'Key']: 'test-token' },
      wx: {
        uploadFile(options) {
          setTimeout(
            () =>
              options.success({
                statusCode: 504,
                data: JSON.stringify({
                  detail: { code: 'parse_timeout', message: '识别超时，请重试' },
                }),
              }),
            0
          );
          return { abort() {} };
        },
      },
    });
    const realApi = apiRt.load('utils/api.js');
    const err = await realApi
      .uploadWithTask('/api/courses/parse-image', { filePath: 'x.png' })
      .done.then(
        () => null,
        (e) => e
      );
    assert.strictEqual(err.statusCode, 504);
    assert.strictEqual(err.code, 'parse_timeout');
    assert.match(err.message, /识别超时/);
  });

  console.log(`\n全部通过：${passed} 项`);
}

main().catch((err) => {
  console.error('FAIL:', err.message);
  process.exit(1);
});
