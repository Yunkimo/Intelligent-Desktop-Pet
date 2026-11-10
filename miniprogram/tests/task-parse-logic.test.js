// C8 验收（逻辑层）：驱动真实 utils/task_parse.js。
// - 参考时刻构造（带偏移 + 明确时区）
// - 缺项/过去时间标记、载荷只带 title/note/due_at/remind_at
// - 逐项保存：成功/明确失败/响应不明核对列表，不自动重放
// 由 tests/run-tests.js 以独立进程运行（node tests/task-parse-logic.test.js）。

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
const tp = rt.load('utils/task_parse.js');

const DRAFT = {
  title: '交实验报告',
  note: '',
  source: '明天下午三点提醒我交实验报告',
  due_at: null,
  remind_at: '2026-10-31T15:00:00+08:00',
  needs_confirmation: [],
};

async function main() {
  await check('buildReference：本机当前时间带偏移且时区明确', () => {
    const ref = tp.buildReference();
    assert.match(ref.reference_at, /^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}[+-]\d{2}:\d{2}$/);
    assert.strictEqual(ref.timezone, 'Asia/Shanghai');
  });

  await check('needsText：日期不明/时刻不明/提醒时刻不明/已过去映射为中文', () => {
    assert.strictEqual(tp.needsText({ needs_confirmation: [] }), '');
    assert.strictEqual(tp.needsText({ needs_confirmation: ['date'] }), '日期不明');
    assert.strictEqual(tp.needsText({ needs_confirmation: ['time'] }), '仅有时刻，未说明要提醒');
    assert.strictEqual(tp.needsText({ needs_confirmation: ['remind_at'] }), '提醒时刻不明');
    assert.strictEqual(tp.needsText({ needs_confirmation: ['past'] }), '时间已过去');
    assert.strictEqual(
      tp.needsText({ needs_confirmation: ['date', 'past'] }),
      '日期不明、时间已过去'
    );
  });

  await check('toTaskPayload：只带四个字段，空值转 null，去除解析专用字段', () => {
    assert.deepStrictEqual(
      plain(
        tp.toTaskPayload({
          ...DRAFT,
          due_at: '',
          note: '  ',
          source: '原文',
          needs_confirmation: ['x'],
        })
      ),
      { title: '交实验报告', note: '', due_at: null, remind_at: '2026-10-31T15:00:00+08:00' }
    );
  });

  await check('saveDrafts：逐项保存成功并返回任务', async () => {
    const calls = [];
    const api = {
      createTask: async (payload) => {
        calls.push(payload);
        return { id: calls.length, ...payload };
      },
    };
    const { statuses, uncertain } = await tp.saveDrafts(
      [DRAFT, { ...DRAFT, title: '第二条' }],
      api
    );
    assert.strictEqual(uncertain, false);
    assert.strictEqual(calls.length, 2);
    assert.deepStrictEqual(plain(statuses.map((s) => [s.status, s.task && s.task.id])), [
      ['created', 1],
      ['created', 2],
    ]);
  });

  await check('saveDrafts：4xx 为明确失败并保留原因，其余条目不受影响', async () => {
    const api = {
      createTask: async (payload) => {
        if (payload.title === '坏条目') {
          const error = new Error('HTTP 422');
          error.statusCode = 422;
          throw error;
        }
        return { id: 1, ...payload };
      },
    };
    const { statuses } = await tp.saveDrafts(
      [DRAFT, { ...DRAFT, title: '坏条目' }, { ...DRAFT, title: '好条目2' }],
      api
    );
    assert.deepStrictEqual(plain(statuses.map((s) => [s.draft.title, s.status])), [
      ['交实验报告', 'created'],
      ['坏条目', 'failed'],
      ['好条目2', 'created'],
    ]);
    assert.deepStrictEqual(plain(tp.failedDrafts(statuses).map((d) => d.title)), ['坏条目']);
  });

  await check('saveDrafts：网络失败先核对列表，一致视为已创建，不自动重放', async () => {
    let createCalls = 0;
    const existing = {
      title: '已存在任务',
      due_at: '',
      remind_at: '2026-10-31T15:00:00+08:00',
    };
    const api = {
      createTask: async () => {
        createCalls += 1;
        throw new Error('网络失败');
      },
      getTasks: async () => [existing],
    };
    const { statuses, uncertain } = await tp.saveDrafts(
      [
        { ...DRAFT, title: '已存在任务' },
        { ...DRAFT, title: '不确定任务' },
      ],
      api
    );
    assert.strictEqual(uncertain, true);
    assert.strictEqual(createCalls, 2, '每条只尝试一次，核对后不重放');
    assert.deepStrictEqual(plain(statuses.map((s) => [s.draft.title, s.status])), [
      ['已存在任务', 'created'],
      ['不确定任务', 'uncertain'],
    ]);
  });

  await check('saveDrafts：核对列表也不可达时全部保持待确认', async () => {
    const api = {
      createTask: async () => {
        throw new Error('网络失败');
      },
      getTasks: async () => {
        throw new Error('仍不可达');
      },
    };
    const { statuses } = await tp.saveDrafts([DRAFT], api);
    assert.strictEqual(statuses[0].status, 'uncertain');
    assert.deepStrictEqual(plain(tp.failedDrafts(statuses).map((d) => d.title)), ['交实验报告']);
  });

  console.log(`\n全部通过：${passed} 项`);
}

main().catch((err) => {
  console.error('FAIL:', err.message);
  process.exit(1);
});
