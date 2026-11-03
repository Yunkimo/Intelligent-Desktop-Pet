// 每周固定安排（逻辑层）：从提醒列表挑出 repeat_rule=weekly 的未完成项，
// 换算成「周几 + 时间」并按周一到周日排序。
// 由 tests/run-tests.js 以独立进程运行（node tests/weekly-logic.test.js）。

const assert = require('assert');
const { runtime } = require('./runtime');

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
  assert.deepStrictEqual(result.map((item) => item.id), [1]);
});

check('换算出周几与时间', () => {
  const [item] = weekly.weeklyReminders([reminder({ remind_at: '2026-11-01T19:00' })]);
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
  assert.deepStrictEqual(
    result.map((item) => item.weekday + item.time),
    ['周一07:30', '周三09:00', '周日19:00']
  );
});

check('非数组与空值不会抛错', () => {
  assert.deepStrictEqual(weekly.weeklyReminders(undefined), []);
  assert.deepStrictEqual(weekly.weeklyReminders([]), []);
});

console.log(`weekly logic: ${passed} passed`);
