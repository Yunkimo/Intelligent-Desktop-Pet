// 测试运行器：以独立进程依次运行各逻辑验收测试，汇总退出码。
// 用法：node tests/run-tests.js（CI 与本地一致）

const { spawnSync } = require('child_process');
const path = require('path');

// 同时保留 WebSocket 适配层和 C3 订阅恢复回归。
const TEST_FILES = ['ws-logic.test.js', 'subscribe-logic.test.js'];

let failed = 0;
for (const file of TEST_FILES) {
  const result = spawnSync(process.execPath, [path.join(__dirname, file)], {
    stdio: 'inherit',
  });
  if (result.status !== 0) {
    failed += 1;
    console.error(`FAIL ${file}（退出码 ${result.status}）`);
  }
}

if (failed > 0) {
  console.error(`\n${failed}/${TEST_FILES.length} 个测试文件失败`);
  process.exit(1);
}
console.log(`\n全部测试文件通过（${TEST_FILES.length}/${TEST_FILES.length}）`);
