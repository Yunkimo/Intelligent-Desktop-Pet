# CI 检查、结果留存与本地复现

配置：[ci.yml](../.github/workflows/ci.yml)。C5先核对现有成果，再补缺口；CI执行测试，不是自动部署，不会连接真实服务器、微信或收费模型。共享工作流变更由PR提交成员复核后合并，C5不代替审批。

## 触发与权限

- push到main/develop触发；任何pull_request触发。仅push功能分支而未建PR时不自动运行，不能把没有run记作成功。
- 并发按github.ref分组，更新同一PR会取消旧运行；最终核对对应SHA的新run。
- GITHUB_TOKEN仅声明contents:read；没有SSH发布、部署环境或生产密钥步骤。

## 复用与增量

| job | 复用的检查 | C5增量与结果 |
|---|---|---|
| miniprogram-c3 | Node22、lint、格式、WS/C3逻辑与真实后端恢复（只Mock微信上游） | 保留检查输出，pipefail防止tee掩盖失败 |
| backend | Python3.10/3.12、Ruff、pytest覆盖率、WS/调度/微信/查询/压缩冒烟、密钥扫描、审计 | JUnit、覆盖率XML；3.12审计JSON |
| desktop | Python3.12、Qt offscreen+xvfb、Ruff、pytest及审计 | JUnit、覆盖率XML、审计JSON |
| deployment-docs | 复用C4已实现的部署测试 | 新接入文档检查、真实临时Nginx/TLS/上传/鉴权/备份/回滚；全Git历史支持历史schema测试 |

原先三类job共四个执行（backend双版本），新增一类后共五个执行。没有重复搭建后台/桌宠测试，也不把复用C4用例算成C5新增部署功能。

## 归档

各job以always()上传ci-results下的测试产物，保留14天。名字为miniprogram-results、backend-py3.10-results、backend-py3.12-results、desktop-results、deployment-docs-results。只有实际产生的文件才上传；更早的安装/静态检查失败可能无产物，仍以步骤日志和run结论判定。

只归档JUnit、覆盖率、审计JSON和检查输出；不归档工作目录、.env、config.js、数据库或真实个人数据。通过并不等于平台真机/音频/正式HTTPS或许可证兼容已经验收。

[GitHub归档下载说明](https://docs.github.com/en/actions/how-tos/manage-workflow-runs/download-workflow-artifacts)：从对应Actions run的Artifacts下载，需要仓库读取权限；过期后链接不保证能下载，关键结论另存[C5记录](c5-verification.md)。

## 本地命令

从仓库根目录使用安装了相应依赖的Python环境。下面为跨平台命令；Linux部署测试需PATH中有nginx和openssl，Windows可显式设置NGINX_BINARY/OPENSSL_BINARY为实际程序路径。缺少程序时部分用例会skip，不计为该能力通过；新增Linux CI先检查二者存在。

```bash
python -m pip install -r backend/requirements-dev.txt
python scripts/check_docs.py
python scripts/check_c4_docs.py
python -m pytest tests_deployment -q -o addopts= -o junit_family=legacy --junitxml=ci-results/deployment.xml
```

后端与桌宠复现：

```bash
python -m pytest backend/tests --cov=backend/app --cov-report=term
python -m pip install -r requirements-dev.txt
python -m pytest tests -q
```

Linux无图形会话时使用工作流的xvfb-run与QT_QPA_PLATFORM=offscreen；这不代表真实窗口/扬声器人工通过。小程序：

```bash
npm ci --prefix miniprogram
npm run lint --prefix miniprogram
npm run format:check --prefix miniprogram
npm test --prefix miniprogram
python scripts/check_c3_integration.py
```

审计继续沿用pip-audit，对相应requirements执行，保留其非零失败码。桌宠依赖下限会导致解析版本变化，不能把某个旧审计当作永久无漏洞结论。

## 文档检查边界

check_docs.py覆盖根目录Markdown、docs下Markdown、assets/README与miniprogram/README；检查UTF-8、相对文件链接存在、代码围栏成对，忽略围栏/行内示例链接、外部URL、绝对链接和锚点。它不读取agent/AGENTS指令文件、私有配置、node_modules或虚拟环境，也不执行文档中的命令。

检查器有真实缺失链接、未闭合围栏、转义路径及示例排除回归。命令有效性另外按已知入口/测试核对，Markdown通过不等于所有业务或外部网址都已验证。
