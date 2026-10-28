// 仅供微信开发者工具/IP 调试使用，操作见 docs/C4-IP调试复验.md。
// 复制为 config.js；已有 config.js 时只修改 baseUrl，保留自己的 apiKey。
// 8080 是本次选择的 Nginx 调试端口，需先在实际服务器启用并验证可达。
module.exports = {
  baseUrl: 'http://8.148.29.9:8080',
  // 填入当前服务器 API_TOKEN；仅用临时演示凭据与数据，不提交真实配置。
  apiKey: 'change-me-to-a-random-string', // pragma: allowlist secret
};
