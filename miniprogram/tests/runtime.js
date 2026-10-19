// 在隔离的模块缓存中加载真实小程序文件，不覆盖开发者的 config.js。
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const root = path.resolve(__dirname, '..');
function runtime({ config = {}, api, wx = {} } = {}) {
  const cache = new Map();
  const storage = new Map();
  let page;
  const platform = {
    getStorageSync: (key) => storage.get(key),
    setStorageSync: (key, value) => storage.set(key, JSON.parse(JSON.stringify(value))),
    removeStorageSync: (key) => storage.delete(key),
    login: ({ success }) => success({ code: 'alice' }),
    requestSubscribeMessage: ({ success }) => success({ test: 'accept' }),
    ...wx,
  };
  function load(name) {
    const filename = path.resolve(root, name);
    if (filename === path.join(root, 'config.js')) {
      return config;
    }
    if (api && filename === path.join(root, 'utils/api.js')) {
      return api;
    }
    if (cache.has(filename)) {
      return cache.get(filename).exports;
    }
    const module = { exports: {} };
    cache.set(filename, module);
    const context = {
      module,
      exports: module.exports,
      wx: platform,
      console,
      setTimeout,
      clearTimeout,
      Date,
      Map,
      Promise,
      Page: (definition) => {
        page = definition;
      },
      getApp: () => ({}),
      require: (relative) =>
        relative.startsWith('.')
          ? load(
              path.resolve(path.dirname(filename), relative + (path.extname(relative) ? '' : '.js'))
            )
          : require(relative),
    };
    vm.runInNewContext(fs.readFileSync(filename, 'utf8'), context, { filename });
    return module.exports;
  }
  function loadPage(name) {
    load(name);
    page.data = JSON.parse(JSON.stringify(page.data));
    page.setData = (data) => Object.assign(page.data, data);
    return page;
  }
  return { load, loadPage, storage, wx: platform, cache };
}
module.exports = { runtime };
