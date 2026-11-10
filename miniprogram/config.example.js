// 复制本文件为 miniprogram/config.js 并填入真实值。
// config.js 已加入 .gitignore —— API Key 属于密钥，不提交进仓库（见 docs/security.md）。
module.exports = {
  // 后端地址：开发期可用局域网 IP 或内网穿透地址（见 docs/deploy.md，任务 C4）
  baseUrl: 'http://127.0.0.1:8001',
  // C9（B8）起业务请求统一使用微信登录会话（Bearer），不再依赖 API Key。
  // apiKey 仅在后端 ALLOW_LEGACY_API_KEY 过渡期映射默认演示用户，可留空。
  // 行尾 pragma 是 detect-secrets 密钥扫描的误报豁免标记（本行仅为示例占位，非真实密钥）
  apiKey: 'change-me-to-a-random-string', // pragma: allowlist secret
  // 微信订阅消息模板 ID（C3）：在微信公众平台「订阅消息」申请模板后填入；
  // 留空时点「订阅提醒」会提示未配置。模板字段映射见 backend/.env 的 WX_TEMPLATE_FIELDS
  subscribeTemplateId: '',
  // 提醒显示及无时区旧数据解释须与后端 REMINDER_NAIVE_OFFSET_MINUTES 一致。
  reminderOffsetMinutes: 480,
  requestTimeoutMs: 15000,
  // 图片识别客户端等待上限（B7 契约：服务端预算 60 秒，客户端最多等 70 秒）
  parseTimeoutMs: 70000,
};
