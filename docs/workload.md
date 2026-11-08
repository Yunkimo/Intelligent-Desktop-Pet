# 工作量与协作台账

| 成员 | Issue | 类别 | 预估点数 | 状态 | 证据 | 验收人 |
|---|---|---|---:|---|---|---|
| A / Yunkimo | [#1](https://github.com/Yunkimo/Intelligent-Desktop-Pet/issues/1) | BackendClient（httpx REST + X-API-Key） | 待团队确认 | 已完成 | PR [#17](https://github.com/Yunkimo/Intelligent-Desktop-Pet/pull/17)，`3385fe5`/`7905385` | 待 B/C 评审 |
| A / Yunkimo | [#2](https://github.com/Yunkimo/Intelligent-Desktop-Pet/issues/2) | Agent 工具调用（function calling + 工具循环 + 联网查询） | 待团队确认 | 已完成 | PR [#17](https://github.com/Yunkimo/Intelligent-Desktop-Pet/pull/17)，`67de45f`/`94861b7` | 待 B/C 评审 |
| A / Yunkimo | [#3](https://github.com/Yunkimo/Intelligent-Desktop-Pet/issues/3) | 健康关怀（久坐提醒） | 待团队确认 | 已完成 | PR [#17](https://github.com/Yunkimo/Intelligent-Desktop-Pet/pull/17)，`c273278`→`9ff1bef` | 待 B/C 评审 |
| A / Yunkimo；本轮修复 wwweiliang | [#4](https://github.com/Yunkimo/Intelligent-Desktop-Pet/issues/4) | 实时接收及用户授权的去重/语音补全 | 待团队确认，不重复计点 | 联调通过，待评审 | 原 PR [#17](https://github.com/Yunkimo/Intelligent-Desktop-Pet/pull/17)；修复 PR [#21](https://github.com/Yunkimo/Intelligent-Desktop-Pet/pull/21)、[验收数据](evidence/b2/)（汇总见 [测试文档](testing.md) §5.2） | 未冒充独立评审 |
| B / wwweiliang | [#5](https://github.com/Yunkimo/Intelligent-Desktop-Pet/issues/5) | WebSocket 广播，含测试与接口文档 | 5（守则初始估算，待团队确认） | 已合并，验收记录待补 | [PR #16](https://github.com/Yunkimo/Intelligent-Desktop-Pet/pull/16)、[测试文档](testing.md)、[契约](api-contract.md) | 待 A/C 确认 |
| B / wwweiliang | [#6](https://github.com/Yunkimo/Intelligent-Desktop-Pet/issues/6) | 提醒调度、故障恢复、迁移及量化验证 | 8（守则初始估算，待团队确认） | 联调通过，待评审 | 功能 cbd0f63、[验收数据](evidence/b2/)（汇总见 [测试文档](testing.md) §5.2） | 未冒充独立评审 |

2026-10-12 核验：B1 的 PR #16 已合并到 develop；GitHub reviews 接口未返回独立评审记录，
不据合并动作补造人工评审或三端验收。#5 议题仍打开。

实际工时未人工登记；验收点数尚未确认，各条目「预估点数」待团队统一口径后填写。
代码、测试和文档均属于同一成果，不重复计分。C（YingboQi）的 C1–C5 条目待其完成后补录。
未形成最终绩效比例，不以代码行数或提交数推算个人成绩。

## B3 工作量增量（2026-10-14）

| 成员 | Issue | 交付与可追溯证据 | 初估 | 状态 |
|---|---|---|---|---|
| B / wwweiliang | [#7](https://github.com/Yunkimo/Intelligent-Desktop-Pet/issues/7) | 微信适配器、身份/会话、持久授权状态、59 项新增自动化、Mock 演示脚本、CI 步骤和图文报告 | 8 点，待团队确认 | 实现与本地验证完成，待评审、C3 真机联调 |

计量使用 Issue 验收项、PR 中的代码/测试/文档差异及执行证据，不只统计代码行或提交次数；本次 59 项测试计入 B3 的同一成果，不重复加分。B 负责后端和故障测试，C 负责小程序授权流程与部署/真机证据，独立评审由其他成员署名。实际工时、验收点数及绩效比例尚未由团队确认；没有代填他人贡献。分配建议仍按已验收任务的复杂度、实现、设计、测试和评审贡献综合确认，避免只奖励提交业务代码的人。
## B4 增量（2026-10-15）

| 成员 | Issue | 交付与证据 | 初估 | 状态 |
|---|---|---|---|---|
| B / wwweiliang | [#8](https://github.com/Yunkimo/Intelligent-Desktop-Pet/issues/8) | 后端天气/搜索适配器与契约、63 项测试、真实 curl 脚本、CI 及图文报告 | 5 点，待团队确认 | 实现与本地验收通过，待评审和 A/C 接入确认 |

B4 原为可选，按用户明确要求纳入本轮。代码、测试、设计、安全及文档作为一个成果核算，不因用例数或提交数重复加分；复用的 SQLite 测试稳定性修正不重复申报 B3/B4 工作量。A 的现有本地联网实现归 A，B 的后端接口归 B，后续接入与评审按实际贡献记录。工时、验收点数及绩效比例尚待团队确认，不代填其他成员记录。

## 范围调整记录（2026-10-17，用户指示）

- 原 C5 的阶段文档（README 快速开始、用户手册、架构图）、CI 维护（miniprogram JS 检查 job）与
  现阶段依赖/安全说明（THIRD_PARTY_NOTICES、security 部署边界）按新任务书移入 C4（Issue #12），
  相关工作只计入 C4，不重复计分；调整后估算由团队确认。
- C5（Issue #13）保留最终版本验收、完整演示视频与交付材料汇总，当前暂缓，不标记完成。
- C3（Issue #11）与 C4（Issue #12）以独立 PR 分别交付（PR #43 / #44）。

## C5 范围与本轮交付（2026-10-25，覆盖前述旧范围）

2026-10-23的任务调整已把阶段文档、CI维护、依赖与安全说明从C4移回C5，并删除C5原最终验收/视频/材料总汇工作。上文将这些内容移入C4及暂缓C5的段落保留为历史，不作为当前计分归属。

| 成员 | Issue | 本轮成果 | 状态与证据 | 点数/工时 |
|---|---|---|---|---|
| C / YingboQi | [#13](https://github.com/Yunkimo/Intelligent-Desktop-Pet/issues/13) | 阶段文档同步、复用CI并补文档/部署回归与结果归档、依赖素材许可/安全边界 | 实现、41项部署文档回归与实际CI五个执行通过；用户已确认人工核验通过，见[C5记录](c5-verification.md)及PR #63；共享CI变更待成员PR复核 | 待团队确认，不代填 |

C4部署事实与演练仅引用[既有C4记录](c4-verification.md)，不在C5重复计算工作量；A/B模块事实仍归原模块，不以本轮编辑代填其完成状态。

## V2 工作量与绩效口径

统计基线是发布提交 `a11a420`。用以下命令统计从仓库起点到 V2 的非合并提交，作者名取 Git 元数据。

```powershell
git log --no-merges --format=%an a11a420 |
  Group-Object | Sort-Object Count -Descending | Select-Object Name,Count
git log --no-merges --numstat a11a420 -- pet backend miniprogram docs tests tests_deployment
```

| 成员 | Git 作者名及提交数 | 代表性交付与验证证据 |
| --- | --- | --- |
| A / Yunkimo | `Yunkimo` 108 | 桌宠文字录入与确认交互，含 Qt 回归和标题清理。 [Issue #116](https://github.com/Yunkimo/Intelligent-Desktop-Pet/issues/116) · [PR #117](https://github.com/Yunkimo/Intelligent-Desktop-Pet/pull/117) · `54346d8` |
| B / wwweiliang | `wwweiliang` 54 | WebSocket 同步及账号隔离，含验收证据、接口设计与故障场景。 [Issue #5](https://github.com/Yunkimo/Intelligent-Desktop-Pet/issues/5) · [PR #16](https://github.com/Yunkimo/Intelligent-Desktop-Pet/pull/16) · 验证记录提交 `b180c7d` |
| C / YingboQi | `Yingbo Qi` 74，`YingboQi` 7，共 81 | 部署、回归、架构文档与供应链说明。 [Issue #13](https://github.com/Yunkimo/Intelligent-Desktop-Pet/issues/13) · [PR #63](https://github.com/Yunkimo/Intelligent-Desktop-Pet/pull/63) · `52257a5`、`c44a90f` |
| 未归属 | `Your Name` 5 | Git 元数据没有可确认的成员名，单列待核对 |

每项工作由成员在 Issue 记录负责人、验收条件、预估复杂度与协作者。完成后关联 PR、设计稿或用例、CI 或实测结果，并记录复核人。代码增删行和提交数用于复核变更规模与覆盖面。测试、设计、文档和复核人员可通过其署名提交、PR 评论或 Issue 验收记录展示贡献。

### 绩效分配建议

按已验收任务分配。任务开工前由团队共同评估复杂度（1、2、3、5、8 点）。验收时确认每项任务各成员份额，总和为 100%，覆盖设计、实现、测试、文档和评审。成员积分为各任务点数乘个人份额后相加，建议绩效比例为个人积分占全体积分的比例。用同一任务份额反映协作可避免一份成果重复计量，也能让设计和测试按实际交付计分。任务点、个人份额与最终绩效均待团队核定。
