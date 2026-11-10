// C8 验收（契约/联调层）：由 scripts/check_c8_integration.py 启动真实后端（临时数据库）。
// 真实 utils/api.js + utils/task_parse.js + 日程页真实逻辑：
// - 任务书固定样例：参考 2026-10-30 12:00，「明天下午三点提醒我交实验报告」→
//   10-31 15:00 提醒；「下周五前交报告」→ 11-06 截止且不生成提醒
// - 缺项/过去时间标记、鉴权与 422 错误
// - 页面真实流程：一句话 → 草稿 → 确认保存 → 读回；带提醒日程只有一条 PC 关联
// - 逐项保存失败保留、响应不明核对列表

const assert = require('node:assert/strict');
const { runtime } = require('./runtime');

const baseUrl = 'http://127.0.0.1:' + process.env.C8_TEST_PORT;
const token = process.env.API_TOKEN;
if (!process.env.C8_TEST_PORT) {
  throw new Error('请运行 python scripts/check_c8_integration.py');
}

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
    showToast: (opts) => toasts.push(opts.title),
    showLoading: () => {},
    hideLoading: () => {},
    showModal: () => {},
  },
});
const api = rt.load('utils/api.js');
const tp = rt.load('utils/task_parse.js');

let passed = 0;
async function check(name, fn) {
  await fn();
  passed += 1;
  console.log('PASS ' + name);
}

async function raw(path, method = 'GET', body) {
  // C9 起业务接口用会话：先确保登录，再带 Bearer（X-API-Key 仅供鉴权冒烟用例）
  await api.getCourses();
  const sessionToken = rt.load('utils/session.js').token();
  const response = await fetch(baseUrl + path, {
    method,
    headers: {
      'X-API-Key': token,
      'Content-Type': 'application/json',
      ...(sessionToken ? { Authorization: 'Bearer ' + sessionToken } : {}),
    },
    body: body ? JSON.stringify(body) : undefined,
  });
  const text = await response.text();
  return { status: response.status, data: text ? JSON.parse(text) : null };
}

async function cleanupTasks(titles) {
  for (const task of await api.getTasks()) {
    if (titles.includes(task.title)) {
      await api.deleteTask(task.id);
    }
  }
}

async function main() {
  await check('任务书固定样例：明天下午三点→10-31 15:00；下周五前→11-06 截止且无提醒', async () => {
    const result = await raw('/api/tasks/parse-text', 'POST', {
      text: '明天下午三点提醒我交实验报告；下周五前交报告',
      reference_at: '2026-10-30T12:00:00+08:00',
      timezone: 'Asia/Shanghai',
    });
    assert.equal(result.status, 200);
    assert.equal(result.data.drafts.length, 2);
    assert.equal(result.data.drafts[0].remind_at, '2026-10-31T15:00:00+08:00');
    assert.equal(result.data.drafts[0].due_at, null);
    assert.equal(result.data.drafts[1].due_at, '2026-11-06');
    assert.equal(result.data.drafts[1].remind_at, null, '只说截止日期不自动加提醒');
    assert.equal(result.data.drafts[1].needs_confirmation.includes('remind_at'), false);
  });

  await check('缺项与过去时间标记：无日期标 date，昨天标 past', async () => {
    const noDate = await raw('/api/tasks/parse-text', 'POST', {
      text: '交实验报告',
      reference_at: '2026-10-30T12:00:00+08:00',
      timezone: 'Asia/Shanghai',
    });
    assert.equal(noDate.data.drafts[0].needs_confirmation.includes('date'), true);
    const past = await raw('/api/tasks/parse-text', 'POST', {
      text: '昨天下午三点提醒我交报告',
      reference_at: '2026-10-30T12:00:00+08:00',
      timezone: 'Asia/Shanghai',
    });
    assert.equal(past.data.drafts[0].needs_confirmation.includes('past'), true);
  });

  await check('parse-text 鉴权与 422：无 Key 401、空文本 422、未知字段 422', async () => {
    const noKey = await fetch(baseUrl + '/api/tasks/parse-text', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        text: 'x',
        reference_at: '2026-10-30T12:00:00+08:00',
        timezone: 'Asia/Shanghai',
      }),
    });
    assert.equal(noKey.status, 401);
    assert.equal(
      (
        await raw('/api/tasks/parse-text', 'POST', {
          text: '  ',
          reference_at: '2026-10-30T12:00:00+08:00',
          timezone: 'Asia/Shanghai',
        })
      ).status,
      422
    );
    assert.equal(
      (
        await raw('/api/tasks/parse-text', 'POST', {
          text: 'x',
          reference_at: '2026-10-30T12:00:00+08:00',
          timezone: 'Asia/Shanghai',
          extra: 1,
        })
      ).status,
      422
    );
  });

  await check('日程页真实流程：一句话→草稿→确认保存→读回且只有一条 PC 提醒', async () => {
    const page = rt.loadPage('pages/task/task.js');
    await page.load();
    page.openTextInput();
    page.setData({ parseText: '明天下午三点提醒我交实验报告；下周五前交报告' });
    await page.parseText();
    assert.equal(page.data.parseStage, 'draft');
    assert.equal(page.data.draftViews.length, 2);
    assert.match(page.data.draftViews[0].remindText, /^提醒 \d{4}-\d{2}-\d{2} 15:00$/);
    assert.match(page.data.draftViews[1].dueText, /^截止 \d{4}-\d{2}-\d{2}$/);
    assert.equal(page.data.draftViews[1].remindText, '');
    await page.confirmParseSave();
    assert.equal(page.data.parseStage, '');
    const tasks = await api.getTasks();
    const report = tasks.find((t) => t.title === '交实验报告');
    const due = tasks.find((t) => t.title === '交报告');
    assert.ok(report, '提醒任务已落库');
    assert.ok(due, '截止任务已落库');
    assert.ok(report.remind_at, '提醒时间已写入');
    assert.equal(due.remind_at, null, '纯截止任务不生成提醒');
    // 带提醒日程只有一条 PC 关联（后端原子创建，客户端未单独建提醒）
    const pcReminders = (await api.getReminders()).filter(
      (r) => r.task_id === report.id && r.channel === 'pc'
    );
    assert.equal(pcReminders.length, 1);
    await cleanupTasks(['交实验报告', '交报告']);
  });

  await check('逐项保存：4xx 明确失败保留，网络失败核对列表不重复创建', async () => {
    const bad = await tp.saveDrafts(
      [{ title: '坏提醒', note: '', due_at: null, remind_at: 'bad-time' }],
      api
    );
    assert.equal(bad.statuses[0].status, 'failed');
    // 网络失败 + 列表核对：已存在任务视为已创建
    const created = await api.createTask({
      title: '核对任务',
      note: '',
      due_at: null,
      remind_at: null,
    });
    const flaky = {
      createTask: async () => {
        throw new Error('网络失败');
      },
      getTasks: () => api.getTasks(),
    };
    const { statuses } = await tp.saveDrafts(
      [{ title: '核对任务', note: '', due_at: null, remind_at: null }],
      flaky
    );
    assert.equal(statuses[0].status, 'created');
    await api.deleteTask(created.id);
  });

  console.log(`\n全部通过：${passed} 项`);
}

main().catch((err) => {
  console.error('FAIL:', err.message);
  process.exit(1);
});
