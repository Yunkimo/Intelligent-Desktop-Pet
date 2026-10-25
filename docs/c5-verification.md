# C5 阶段文档、CI与依赖说明交付记录

依据[Issue #13](https://github.com/Yunkimo/Intelligent-Desktop-Pet/issues/13)和[C任务书](tasks/C-miniprogram-deploy.md)的C5范围。基线为已推送C4的2dd5ed3c2b83caf1dfb8ae3c6cc43c48173c17be；新分支feat/c5-stage-docs，以C4分支为依赖，C5差异单独评审。

## 范围和归属

C5只整理当前文档事实、复用/补充CI和依赖安全说明。C4手机联调、时延、图片、重启/备份/回滚及另一成员复现保留[原记录](c4-verification.md)，不在这里重复计分。没有最终版本冻结、完整演示视频或课设材料总汇。没有改真实服务器、微信后台、私有配置或用户Key。

## 交付

| 要求 | 具体更新 |
|---|---|
| README与用户手册 | 保留已有配置的启动命令、部署入口与旧热重载入口差别、当前模型示例、现有小程序功能与故障排查 |
| 架构与数据流 | 三端/外部服务图、当前IP代理拓扑、识别确认后落库时序；历史A重构数字保留历史语义 |
| CI核验与维护 | 复用原三类job及四个执行，新增deployment-docs；归档检查输出/JUnit/覆盖率/审计，详见[CI说明](ci.md) |
| 依赖和素材许可 | 补齐桌宠12个直接依赖及关键二进制组件，锁文件78个npm开发包条目，纠正后端certifi/multipart记录，素材和模型未知项明确列出 |
| 安全说明 | 真实外部数据流、HTTP明文、共享鉴权、日志脱敏、备份和CI产物边界，不作全部安全通过结论 |

## 实际CI事实

先读取到develop基线SHA 9bca38fe8e37829d1dda111e4d1063bea3b68b9a的实际push CI：[40117685625](https://github.com/Yunkimo/Intelligent-Desktop-Pet/actions/runs/40117685625)，completed/success，见[原始元数据](evidence/c5/baseline-ci.json)。只返回PR运行的接口未列出该push run，不能据此说基线无CI。

本轮通过[PR #63](https://github.com/Yunkimo/Intelligent-Desktop-Pet/pull/63)单独交付。首次[CI 40183173897](https://github.com/Yunkimo/Intelligent-Desktop-Pet/actions/runs/40183173897)中原四个执行通过，新增部署回归33通过/2失败，均为TLS WS业务握手/重连超时，见[失败记录](evidence/c5/ci-initial-failure.json)。本机复现后将自检HTTP/WS收发统一到异步事件循环，保留CA校验、鉴权、事件及清理断言，并连续三轮验证TLS业务连接；测试服务协议与正式启动器一致。修复源码[5da500c](https://github.com/Yunkimo/Intelligent-Desktop-Pet/commit/5da500cc692e29beb743cb602a3528c10baa3cab)对应的[CI 40184345422](https://github.com/Yunkimo/Intelligent-Desktop-Pet/actions/runs/40184345422)已completed/success：小程序、后端3.10、后端3.12、桌宠、部署文档五个执行全部通过，部署文档35/35通过（23.30秒，0跳过）。五份结果产物均已上传，保留14天，job链接/产物ID及到期时间见[运行记录](evidence/c5/ci-run.json)。此后补写本记录的文档提交另以PR最新CI核对，不将尚未运行的提交冒充已测试源码。共享CI配置需成员在PR中复核，不自动合并。

## 本地检查

本轮Windows/Python3.13本地：修复后完整隔离部署与文档回归35/35通过（103.31秒，0跳过，含原C4用例与新增5个文档检查用例）；[最终输出](evidence/c5/local-deployment-final.txt)与[JUnit](evidence/c5/local-deployment-final.xml)。首次本地通过的[原始输出](evidence/c5/local-deployment.txt)仍保留；其两个record_property格式警告已用legacy JUnit格式处理。一次本地通过不能排除间歇问题，连续TLS回归和上述Linux真实CI现均已通过。

文档检查34份/272个相对链接、既有C4文档6份/114个相对链接通过；Ruff/格式171个Python文件通过；小程序lint/格式/WS与C3逻辑通过，见[前端输出](evidence/c5/local-miniprogram.txt)。五个已记录运维CLI的--help入口返回0；没有执行文档中的任意命令或在真实服务器做新部署。命令入口与环境见[CI说明](ci.md)，不把这些结果当C4业务或微信送达验收。

## 未知项与边界

- Rice.png、tray.webp上游授权尚无依据，已记录引入历史与待补归属；不宣称可商用。
- PyQt6为GPLv3/商业双许可，本机为GPL发行包；Qt、媒体二进制与具体模型权重仍按实际分发物核对，不宣布整体MIT兼容。
- 桌宠requirements未完全锁定；本机后端辅助环境certifi旧于锁文件，许可元数据快照不等于安装匹配或最新审计成功。
- C3真机消息送达等结果沿用各模块证据，不由C5代填完成。C4按用户约定IP开发调试范围完成，不据此声称正式发布通过。

许可来源见[第三方声明](../THIRD_PARTY_NOTICES.md)，原始元数据保存在evidence/c5。C5实现、本地检查与实际CI证据已交付，等待成员PR评审；不代替共享配置的复核，也不自动关闭Issue。

C4证据与摘要绑定其既有交付提交，不拿C4摘要比较C5修改后的文档。本轮另存[源码校验清单](evidence/c5/source-checksums.sha256)，不混改C4原始记录。
