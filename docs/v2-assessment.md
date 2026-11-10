# V2 评分要点与证据

发布基线为 [V2.0.0](https://github.com/Yunkimo/Intelligent-Desktop-Pet/releases/tag/v2.0.0)（`a11a420`）。本页将评分项对应到验收入口，分阶段数据沿用各自报告中的测试条件。

| 类别 | # | 检查项 | 检查入口与证据 |
| --- | ---: | --- | --- |
| Git | 1 | 代码风格 | [贡献指南](../CONTRIBUTING.md)、[EditorConfig](../.editorconfig)、[Ruff 规则](../pyproject.toml)，小程序有 ESLint 与 Prettier |
| Git | 2 | 分支、PR、Issue | [协作流程](../CONTRIBUTING.md#分支与协作流程)、[Issue #116](https://github.com/Yunkimo/Intelligent-Desktop-Pet/issues/116)、[PR #117](https://github.com/Yunkimo/Intelligent-Desktop-Pet/pull/117) |
| Git | 3 | 忽略规则、二进制与日志 | [忽略规则](../.gitignore)、[Git 内容检查](../scripts/check_repo_content.py)。运行 `python -X utf8 scripts/check_repo_content.py --tree HEAD` 检查提交快照 |
| Git | 4 | 许可证、开源供应链 | [MIT 许可证](../LICENSE)、[第三方清单](../THIRD_PARTY_NOTICES.md)、[CI 依赖审计](ci.md) |
| Git | 5 | 参数和路径与逻辑分离 | [配置入口](../README.md#配置位置)、[后端配置](../backend/app/config.py)、[桌宠配置](../pet/config.py)、[小程序配置示例](../miniprogram/config.example.js) |
| Git | 6 | 提交语言一致 | [中文提交规范](../CONTRIBUTING.md#提交规范conventional-commits)，保留英文技术名词 |
| Git | 7 | 单一职责提交 | [暂存与拆分示例](../CONTRIBUTING.md#分支与协作流程) |
| Git | 8 | 提交前格式化 | [pre-commit 配置](../.pre-commit-config.yaml)、[小程序检查](../miniprogram/package.json) |
| Git | 9 | 前后端解耦 | [系统架构](../README.md#系统架构)、[API 契约](api-contract.md) |
| Git | 10 | 部署和演示脚本 | [部署手册](deploy.md)、[演示命令](../README.md#演示与复现)、[Linux 部署入口](../scripts/deploy-server.sh) |
| 文档 | 1 | 用户手册 | [桌宠用户手册](user-manual.md)、[小程序说明](../miniprogram/README.md) |
| 文档 | 2 | 重构收益 | [重构前后对比](refactor-report.md)，移除 Live2D 的提交净减 1,888 行 |
| 文档 | 3 | 实验指标 | [图片识别基准](b7-server-verification.md)、[同步实验](b6-verification.md)、[桌宠时延原始记录](evidence/c4/desktop-latency-20261025.md) |
| 文档 | 4 | 环境参数 | [实验环境](environment.md)，各实验报告记录样本、配置和适用范围 |
| 文档 | 5 | 测试用例 | [人工用例](test-cases.md)、[自动化与复现](testing.md)、[V2 实际 CI](https://github.com/Yunkimo/Intelligent-Desktop-Pet/actions/runs/42465570187) |
| 文档 | 6 | 安全设计 | [安全设计](security.md)、[账号隔离与会话](b8-accounts.md)、[账号隔离验证](b8-verification.md) |
| 文档 | 7 | 系统演示视频 | 本版按要求撤下视频，保留 [演示流程与真机检查](v2-demo.md) |
| 团队 | 1 | 工作量度量 | [工作量台账](workload.md#v2-工作量与绩效口径)，任务验收点、合入提交、评审和复现证据 |
| 团队 | 2 | 绩效分配与理由 | [建议分配规则](workload.md#绩效分配建议)，由团队确认任务点与个人份额后计算 |
| 团队 | 3 | 多人提交 | [V2 非合并提交统计](workload.md#v2-工作量与绩效口径)，按 Git 作者名归档 |
| 团队 | 4 | 设计和测试工作 | [工作样例](workload.md#v2-工作量与绩效口径)，含设计、安全、测试和文档的 Issue、PR、提交 |

内容检查读取 Git 对象，覆盖当前暂存区或指定快照。受跟踪的图片按真实文件签名校验，源码和证据使用 UTF-8 文本。V2 基线含两段 WAV，合计 580,696 字节，本轮改为运行时合成并移除跟踪文件。历史发布快照仍可按原提交复现。
