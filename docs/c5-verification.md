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

本轮通过[PR #63](https://github.com/Yunkimo/Intelligent-Desktop-Pet/pull/63)单独交付。首次[CI 40183173897](https://github.com/Yunkimo/Intelligent-Desktop-Pet/actions/runs/40183173897)中原四个执行通过，新增部署回归33通过/2失败，均为TLS WS业务握手/重连超时，见[失败记录](evidence/c5/ci-initial-failure.json)。本机复现后将自检HTTP/WS收发统一到异步事件循环，保留CA校验、鉴权、事件及清理断言，并连续三轮验证TLS业务连接。修复源码[5da500c](https://github.com/Yunkimo/Intelligent-Desktop-Pet/commit/5da500cc692e29beb743cb602a3528c10baa3cab)对应的[CI 40184345422](https://github.com/Yunkimo/Intelligent-Desktop-Pet/actions/runs/40184345422)已completed/success：小程序、后端3.10、后端3.12、桌宠、部署文档五个执行全部通过，部署文档35/35通过（23.30秒，0跳过）。五份结果产物均已上传，保留14天，job链接/产物ID及到期时间见[运行记录](evidence/c5/ci-run.json)。此后补写本记录的文档提交另以PR最新CI核对，不将尚未运行的提交冒充已测试源码。共享CI配置需成员在PR中复核，不自动合并。

## 本地检查

首次交付Windows/Python3.13本地：修复后完整隔离部署与文档回归35/35通过（103.31秒，0跳过，含原C4用例与新增5个文档检查用例）；[输出](evidence/c5/local-deployment-final.txt)与[JUnit](evidence/c5/local-deployment-final.xml)。更早本地通过的[原始输出](evidence/c5/local-deployment.txt)仍保留；其两个record_property格式警告已用legacy JUnit格式处理。一次本地通过不能排除间歇问题，连续TLS回归和上述Linux真实CI现均已通过。本次二次核验及新增用例结果见文末。

文档检查34份/272个相对链接、既有C4文档6份/114个相对链接通过；Ruff/格式171个Python文件通过；小程序lint/格式/WS与C3逻辑通过，见[前端输出](evidence/c5/local-miniprogram.txt)。五个已记录运维CLI的--help入口返回0；没有执行文档中的任意命令或在真实服务器做新部署。命令入口与环境见[CI说明](ci.md)，不把这些结果当C4业务或微信送达验收。

## 未知项与边界

- Rice.png、tray.webp上游授权尚无依据，已记录引入历史与待补归属；不宣称可商用。
- PyQt6为GPLv3/商业双许可，本机为GPL发行包；Qt、媒体二进制与具体模型权重仍按实际分发物核对，不宣布整体MIT兼容。
- 桌宠requirements未完全锁定；本机后端辅助环境certifi旧于锁文件，许可元数据快照不等于安装匹配或最新审计成功。
- C3真机消息送达等结果沿用各模块证据，不由C5代填完成。C4按用户约定IP开发调试范围完成，不据此声称正式发布通过。

许可来源见[第三方声明](../THIRD_PARTY_NOTICES.md)，原始元数据保存在evidence/c5。C5实现、本地检查与实际CI证据已交付，等待成员PR评审；不代替共享配置的复核，也不自动关闭Issue。

C4证据与摘要绑定其既有交付提交，不拿C4摘要比较C5修改后的文档。本轮另存[源码校验清单](evidence/c5/source-checksums.sha256)，不混改C4原始记录。

## 二次核验（2026-10-25）

按用户要求重新对照代码、文档、CI与证据，发现并修正以下问题：

- 原源码清单按Windows工作区原始字节计算，18项与Git的LF文件不一致。现统一CRLF到LF计算SHA-256，增加可选 `check_docs.py --checksums` 入口及6项回归，覆盖换行兼容、真实内容变化、空清单、格式损坏、缺失和越界目标。
- 手册仍把手机联网概括为同一Wi-Fi，且未说明本机启动器默认仅回环监听。现明确局域网直连的绑定参数和公网入口的网络条件，修正重复复制配置、安装器副作用与旧C3进度描述。
- CI原有Ruff路径遗漏了部署测试目录；现补该目录的静态/格式检查，文档检查输出也归档，并用pipefail保留失败退出码。
- 上次所述“测试协议与启动器一致”不准确：`run_backend.py`使用auto，systemd另有显式协议。已撤回无助于解决握手超时的夹具协议切换，回归再次覆盖本地启动器的默认选择；TLS修复保留异步客户端与全部原断言。

完整部署/文档回归 **41/41通过**（105.93秒，无跳过），见[输出](evidence/c5/review-deployment.txt)和[JUnit](evidence/c5/review-deployment.xml)。按CI说明从仓库根执行后端命令，**252/252通过，覆盖率95%**；出现1项上游Starlette TestClient弃用警告，记录于[后端输出](evidence/c5/review-backend.txt)，未通过更换依赖或屏蔽警告处理它。

另在同一解释器和隔离TLS后端连续执行10轮只读、业务写入、事件、重连及清理检查，**140/140通过**，见[重复检查记录](evidence/c5/review-tls.json)。这些检查均未访问生产服务。二次核验摘要见[review.json](evidence/c5/review.json)；修订提交的远程检查按PR最新SHA和CI链接核对，前述旧运行记录保留其原提交归属。

## 人工核验确认（2026-10-25）

用户（成员C）已明确确认“人工核验通过了”。核验对象为[8b2fe83](https://github.com/Yunkimo/Intelligent-Desktop-Pet/commit/8b2fe83962bd0cbde7e0880e1648083be01bd1b4)，使用该提交的独立源码副本；结果及证据来源见[人工核验记录](evidence/c5/manual-acceptance.json)。

| 项目 | 实际结果 | 证据来源 |
|---|---|---|
| 本地后端健康检查 | 18011端口返回HTTP 200及status:ok | 用户粘贴的终端输出 |
| 无凭据访问业务接口 | GET /api/courses返回HTTP 401 | 用户粘贴的终端输出 |
| 文档与源码检查命令 | 34份文档、278个相对链接、代码围栏、20项源码校验全部通过 | 用户在核验副本执行命令后的输出 |
| GitHub三张图示 | 三端数据流、IP部署拓扑、图片导入时序显示核验通过 | 用户按指引查看后明确确认 |
| 实际CI产物 | XML中tests=41、failures=0、errors=0、skipped=0；两份文档输出均PASS，ZIP摘要与GitHub一致 | 助手实际下载并读取对应Actions产物 |

对应[CI 40198518539](https://github.com/Yunkimo/Intelligent-Desktop-Pet/actions/runs/40198518539)五个执行全部通过。本次只追加验收记录与更新文档清单；核验通过归属C5，不扩大为C3/C4、生产发布或第三方授权的新增验收结论。共享工作流仍按PR进行成员复核，不自动合并。
