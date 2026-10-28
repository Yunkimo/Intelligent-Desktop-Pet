// 全局入口：启动 WebSocket 事件适配层（连接/重连/前后台生命周期见 utils/ws.js），
// 后端配置集中在 utils/api.js 顶部，页面按需调用。
const ws = require('./utils/ws');

App({
  onLaunch() {
    ws.start();
  },
});
