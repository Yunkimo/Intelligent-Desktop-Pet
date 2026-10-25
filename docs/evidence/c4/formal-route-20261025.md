# C4 正式 HTTPS/WSS 诊断与验收边界（2026-10-25）

用户先要求恢复正式路线；收到初始诊断后，最新明确确认ICP备案尚未通过，要求继续通过公网IP验证成果，不使用域名访问服务器。用户随后进一步明确正式HTTPS/WSS不纳入本轮C4验收，不再作为当前待办。没有修改DNS、hosts、服务器Nginx或客户端正式地址，也没有把凭据发往域名。

## 本轮初始只读结果

[原始探测](formal-route-initial-20261025.json)：

- 本机系统DNS没有得到shynb.beer的A记录。
- AliDNS DoH的A查询Status=0、Answer为空、返回SOA；NS为dns19.hichina.com和dns20.hichina.com。Google DoH连接超时，不作为独立解析结论。
- curl仅进程内定向8.148.29.9，保持Host/SNI，严格验证证书，HTTPS连接重置（退出35）。不能判定证书有效，也不能将原因直接归为证书错误。
- 同样定向访问HTTP80，返回403/Server Beaver，响应明确为Non-compliance ICP Filing，属于当前访问路径的备案拦截结果。此请求无凭据。
- 进程内定向只用于隔离DNS问题，不代表正常DNS或微信正式环境通过；没有编辑系统hosts或关闭TLS验证。

## 用户确认与当前采用路线

- 备案：用户明确确认ICP备案尚未通过。
- DNS：用户确认A记录值8.148.29.9已启用。该配置状态来自用户，未在其回复后重新探测公网传播；前文A查询为空是本轮初始实测，不能混称配置不存在或已经传播成功。
- 当前采用http://8.148.29.9:8080和ws://8.148.29.9:8080/ws，沿用小程序开发调试豁免。没有改已可用的私有连接配置。
- 视觉Key配置重启后[最终IP只读复查](ip-route-final-readonly-20261025.json)7/7：健康、REST正负鉴权、真实WS握手及负向拒绝全通过；未创建业务数据。
- 图片真实模型/界面导入删除、5秒内气泡显示、手机CRUD/断网恢复、重启持久化及备份/隔离回滚等既有已通过结果保留，不重复操作。

正式HTTPS/WSS、微信合法域名配置和关闭调试豁免后的真机验收未执行成功，按用户最新要求不纳入本轮C4验收，不再列为当前待办。用户确认另一成员独立复现已成功，见[确认记录](independent-reproduction-user-confirmed-20261025.json)。本轮完成状态限于约定IP开发调试范围，不代表正常域名/证书验收或正式发布通过，也不据此宣称豁免任何平台或备案要求。GitHub Issue状态本次不修改。

## 官方参考

[阿里云域名A记录配置](https://help.aliyun.com/zh/dns/pubz-add-website-parsing)说明根域名@的公网解析设置。[备案阻断排查](https://help.aliyun.com/zh/icp-filing/basic-icp-service/web-site-for-the-record-to-block-1)列出备案状态及接入备案等排查项；当前仅确认响应含备案拦截，不推断用户实际备案订单状态。
