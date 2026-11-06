// 每周固定安排（逻辑层）：从提醒列表挑出 repeat_rule=weekly 的未完成项，
// 换算成「周几 + 时间」并按周一到周日排序。
// 由 tests/run-tests.js 以独立进程运行（node tests/weekly-logic.test.js）。

const assert = require('assert');
const { runtime } = require('./runtime');

// runtime 用 vm 加载模块，返回的对象来自独立 realm：JSON 往返后再比较结构
function plain(value) {
  return JSON.parse(JSON.stringify(value));
}

let passed = 0;
function check(name, fn) {
  fn();
  passed += 1;
  console.log('PASS', name);
}

const rt = runtime();
const weekly = rt.load('utils/weekly.js');

function reminder(overrides) {
  return {
    id: 1,
    title: '跑步',
    body: '',
    remind_at: '2026-11-01T19:00',
    repeat_rule: 'weekly',
    done: 0,
    ...overrides,
  };
}

check('只保留每周且未完成的提醒', () => {
  const result = weekly.weeklyReminders([
    reminder({ id: 1 }),
    reminder({ id: 2, repeat_rule: null }),
    reminder({ id: 3, done: 1 }),
    reminder({ id: 4, remind_at: '' }),
    null,
  ]);
  const ids = plain(result.map((item) => item.id));
  assert.deepStrictEqual(ids, [1]);
});

check('换算出周几与时间', () => {
  const [item] = plain(weekly.weeklyReminders([reminder({ remind_at: '2026-11-01T19:00' })]));
  assert.strictEqual(item.weekday, '周日');
  assert.strictEqual(item.time, '19:00');
  assert.strictEqual(item.title, '跑步');
});

check('按周一到周日排序，同一天按时间', () => {
  const result = weekly.weeklyReminders([
    reminder({ id: 1, remind_at: '2026-11-01T19:00' }),
    reminder({ id: 2, remind_at: '2026-11-04T09:00' }),
    reminder({ id: 3, remind_at: '2026-11-02T07:30' }),
  ]);
  const labels = plain(result.map((item) => item.weekday + item.time));
  assert.deepStrictEqual(labels, ['周一07:30', '周三09:00', '周日19:00']);
});

check('非数组与空值不会抛错', () => {
  assert.deepStrictEqual(plain(weekly.weeklyReminders(undefined)), []);
  assert.deepStrictEqual(plain(weekly.weeklyReminders([])), []);
});

// ===== 一次性提醒并入日程页 =====
check('一次性提醒只保留未完成、非每周、不挂日程的项', () => {
  const result = weekly.oneOffReminders([
    reminder({ id: 1, repeat_rule: null, remind_at: '2026-11-07T10:00' }),
    reminder({ id: 2, repeat_rule: 'weekly' }), // 每周单独处理
    reminder({ id: 3, repeat_rule: null, done: 1 }), // 已完成不显示
    reminder({ id: 4, repeat_rule: null, task_id: 9 }), // 挂在日程下，由日程行展示
    reminder({ id: 5, repeat_rule: null, remind_at: '' }),
    null,
  ]);
  const ids = plain(result.map((item) => item.id));
  assert.deepStrictEqual(ids, [1]);
});

check('一次性提醒按提醒时间排序', () => {
  const result = weekly.oneOffReminders([
    reminder({ id: 1, repeat_rule: null, remind_at: '2026-11-08T10:00' }),
    reminder({ id: 2, repeat_rule: null, remind_at: '2026-11-07T09:00' }),
  ]);
  const ids = plain(result.map((item) => item.id));
  assert.deepStrictEqual(ids, [2, 1]);
});

check('一次性提醒空值安全', () => {
  assert.deepStrictEqual(plain(weekly.oneOffReminders(undefined)), []);
});

console.log(`weekly logic: ${passed} passed`);
