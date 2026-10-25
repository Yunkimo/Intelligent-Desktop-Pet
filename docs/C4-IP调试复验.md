# C4：未完成 ICP 备案时的开发者工具 IP 调试

2026-10-24 用户选择先使用开发者工具“不校验合法域名”进行开发联调。当前入口为 **http://8.148.29.9:8080**，由 Nginx 转发到回环后端 127.0.0.1:8001。10 月 25 日已完成公网有效凭据自检与业务操作 **14/14**、补充修改及清理 **4/4**，包括真实 WS 事件和主动重连，见[公网业务检查](evidence/c4/public-authenticated-checks.json)。此前的[健康结果](evidence/c4/corrected-ip-health.txt)和[负向鉴权结果](evidence/c4/public-negative-checks.json)保留为过程记录。

服务器 systemd 实际重启后记录仍在、WS 可连接，临时记录已清理；备份与恢复到新副本的完整性、结构及条数比较通过。见[重启结果](evidence/c4/server-restart-persistence.json)和[备份副本结果](evidence/c4/server-backup-restore.json)。开发者工具和手机日程/课程 CRUD、手机断网恢复补齐及后续实时刷新已有人工作业和云端核对，见[手机记录](evidence/c4/phone-runtime.json)。合入 develop 后的桌宠气泡/语音已人工观察通过，服务器发送一次并已清理测试提醒；真实模型接口识别、导入/读回/清理已通过，界面识别/确认导入/编辑/删除已通过，见[视觉报告](evidence/c4/vision-recognition-20261025.md)。

2026-10-24 22:21（北京时间）的[旧探测记录](evidence/c4/debug-ip-probe.json)使用了此前提供的错误 IP 8.148.31.9，不能用该超时结论判断实际服务器。下方服务器检查保留为复现步骤，不表示当前仍未启用 8080。

这条路线记录为“公网 IP / HTTP / 开发调试豁免”。它可以推进业务与运维复验；Issue #12 要求的正常域名和证书校验下 HTTPS/WSS、正式部署路线仍单独待验。ICP备案未通过不等于业务代码有错，也不说明公网端口已可访问。

## 1. 服务器先通，再打开微信

在服务器终端确认已有后端：

```bash
curl --fail --max-time 5 http://127.0.0.1:8001/api/health
sudo ss -lntp '( sport = :8001 or sport = :8080 )'
```

预期健康检查返回 `{"status":"ok"}`。失败则先按[服务器操作](C4-服务器操作.md)定位现有服务，不额外启动第二个后端。

用户随后提供服务器实测：127.0.0.1:8001 健康检查 200，8080 Connection refused，Nginx 只监听 80/443。为此新增独立 [8080 调试模板](../deploy/nginx/idp-debug-8080.conf)：在 Ubuntu 标准 Nginx 布局中将它作为新文件放到 /etc/nginx/conf.d/idp-debug-8080.conf（若同名文件已存在则先核对，不直接覆盖）。原 80/443 站点保留；调试模板使用独立日志格式/变量名，代理仍到回环 8001，保持 Upgrade、11m 上传上限和无查询参数的访问日志。只加载一份模板，不另外改旧站点也监听 8080。

```bash
sudo nginx -t
# 只有上一步通过后才执行：
sudo systemctl reload nginx
curl --fail --max-time 5 http://127.0.0.1:8080/api/health
```

在云服务器安全组及系统防火墙中临时允许调试所需的 TCP 8080；后端 8001 保持回环。尽量限制到自己的调试网络。使用临时演示 Key 和数据：HTTP/WS 会明文传输凭据，不适合真实用户数据。

然后在电脑浏览器打开：

```text
http://8.148.29.9:8080/api/health
```

必须能显示健康 JSON。若超时，检查安全组、系统防火墙、Nginx 是否对外监听、上游与服务商实际限制。微信“不校验”开关只改变客户端校验，不会修复这些连通性问题。若服务器实际使用其他端口，统一替换所有调试地址，并记录该端口。

## 2. 修改小程序的本地配置

C4 部署工具目录为 D:/IDP/worktrees/c4-review-package-20261024；其中 miniprogram/config.js 是本机被忽略的凭据配置，也供协作电脑自检读取。

小程序界面复验使用已经人工验证过的 C3 项目。本机现有 C3 目录为 D:/IDP/worktrees/c3-subscription/miniprogram，最终以实际验过的项目为准。C4 评审包的小程序代码基线较旧，部署工具包不携带或覆盖 C3 业务源码；不要将导入旧基线当作更新部署工具的必要步骤。

用户已确认当前工具打开的是 D:/IDP/worktrees/c3-subscription/miniprogram。本机被忽略的 config.js 已更新为云端地址和验证过的服务器凭据，其他配置及业务源码保留。接下来只需核对开发调试开关并重新编译。

其他成员复现时，已有 config.js 只调整连接项；apiKey 必须与服务器 API_TOKEN 一致，原局域网凭据不一定适用。没有时复制 [config.server-debug.example.js](../miniprogram/config.server-debug.example.js) 为 config.js，在本机填写。config.js 不提交、不截图分享。

```javascript
module.exports = {
  baseUrl: 'http://8.148.29.9:8080',
  apiKey: 'change-me-to-a-random-string', // pragma: allowlist secret，仅占位，须在本机填写
};
```

末尾不带斜杠。现有 API/上传/WS 适配层共用这个地址：REST 为 http://8.148.29.9:8080/api/...，图片上传同一地址，WS 自动派生为 ws://8.148.29.9:8080/ws。不要改成 wss，除非该端口确实配置了 TLS。

## 3. 开发者工具勾选并重新编译

1. 导入已经验过的 C3 miniprogram 目录，修改其本机 config.js 并核对是自己的 AppID。
2. 右上角“详情” → “本地设置”。
3. 勾选“不校验合法域名、web-view（业务域名）、TLS 版本以及 HTTPS 证书”（以工具实际文案为准）。
4. 重新编译；记录开发者工具版本、基础库、地址和该开关状态。
5. 先在工具中测试课表/日程读写、另一端创建后的刷新和断网恢复；图片识别用户已恢复配置，界面识别/确认导入/编辑/删除也已完成。

这里只采用用户提供的工具开关方案；本轮[官方网络文档](https://developers.weixin.qq.com/miniprogram/dev/framework/ability/network.html)仍无法通过工具读取。实际菜单及平台行为按当前安装版本观察记录，不把未验证的手机行为写成通过。

## 4. 手机测试单独记录

开发者工具的本地勾选不等于手机自动获得同样的豁免。继续手机测试时，使用开发版/工具提供的真机调试能力，记录手机端实际调试状态；如微信菜单提供“开发调试/打开调试”入口，再按当前客户端界面开启并重进。

当前 TCP 8080 安全组来源只允许电脑公网出口 120.227.60.160。手机先连接与电脑相同的 Wi-Fi，并确认其出口也在放行范围，再用浏览器访问相同健康地址，然后测试小程序。若切换手机流量，需要先核对并单独放行其实际出口；不要把白名单拒绝误判为业务代码故障。如果工具能用而手机报域名、证书或网络错误，保留具体报错和版本，不能把工具成功当作真机通过，也不能保证体验版或正式版沿用调试豁免。

真机当前覆盖：CRUD、另一端创建后页面刷新、断网恢复自动重连并拉取当前状态。用户已替换服务器真实视觉Key并重启；>1MiB有效合成PNG真实模型识别和接口导入/读回/清理通过，界面识别/确认导入/编辑/删除已通过。该文件是元数据扩展体积，真实大照片及正式HTTPS路线仍待补。旧502和示例Key诊断作为历史证据保留，详见[视觉报告](evidence/c4/vision-recognition-20261025.md)。

## 5. 自检与运维继续按 C4 执行

从有服务器凭据配置的终端执行（下面沿用模板安装路径，实际不同须替换）：

```bash
sudo /home/idp/venvs/idp/bin/python /你上传的工具目录/scripts/check_deployment.py \
  http://8.148.29.9:8080 --env-file /home/idp/idp/backend/.env
```

只读预期 7/7，此时验证的是 HTTP/WS。专用演示数据上加 --exercise，预期 14/14，包含临时日程/课程写入、真实事件、主动重连及清理。服务器自身访问公网 IP 若因网络回流限制失败，可先以 http://127.0.0.1:8080 自检，再从另一网络核验公网 IP，分别记录来源，不能互相代替。

重启持久化、单实例、备份恢复/回滚、单条桌宠提醒和另一成员复现继续按[人工复验](C4-人工复验.md)执行。填[验收记录](evidence/c4/acceptance-template.md)时将本路线与正常 HTTPS/WSS 分开。

测试结束后关闭不再需要的公网 HTTP 调试监听与对应放行规则。备案、域名和证书条件就绪后，baseUrl 切回 https://shynb.beer，核对微信后台三类合法域名，关闭调试豁免，再执行正式路线复验。

## 继续使用IP的最终复查

用户确认ICP备案未过，最新要求不使用域名访问服务器。保持现有IP配置及开发调试豁免；视觉Key配置并重启后，IP只读健康/正负鉴权/WS复查7/7通过，见[最终记录](evidence/c4/ip-route-final-readonly-20261025.json)。图片实际识别导入和5秒展示补验均已通过、测试记录已清理。正式HTTPS/WSS与微信正常域名校验仍未验收，详见[边界记录](evidence/c4/formal-route-20261025.md)。无需重复此前已通过的人工CRUD/清理操作。
