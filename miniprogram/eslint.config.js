// 小程序 JS 静态检查配置（ESLint flat config）。
// 微信运行时全局（wx/App/Page/getApp）与 CommonJS 环境在此声明；
// 规则保持克制：只拦语法错误、未定义变量与明显笔误，避免与手写风格冲突。
module.exports = [
  {
    ignores: ['node_modules/**'],
  },
  {
    files: ['**/*.js'],
    languageOptions: {
      ecmaVersion: 2022,
      sourceType: 'commonjs',
      globals: {
        // 微信小程序运行时
        wx: 'readonly',
        App: 'readonly',
        Page: 'readonly',
        getApp: 'readonly',
        // Node（仅 tests/）
        process: 'readonly',
        require: 'readonly',
        module: 'readonly',
        __dirname: 'readonly',
        // 常用全局
        console: 'readonly',
        setTimeout: 'readonly',
        clearTimeout: 'readonly',
        setInterval: 'readonly',
        clearInterval: 'readonly',
        Date: 'readonly',
        Math: 'readonly',
        JSON: 'readonly',
        Promise: 'readonly',
        Number: 'readonly',
        String: 'readonly',
        Array: 'readonly',
        Object: 'readonly',
        Set: 'readonly',
        Map: 'readonly',
        Error: 'readonly',
        encodeURIComponent: 'readonly',
        isNaN: 'readonly',
      },
    },
    rules: {
      'no-undef': 'error',
      'no-unreachable': 'error',
      'no-dupe-keys': 'error',
      'no-func-assign': 'error',
      'no-unused-vars': 'off',
      'no-empty': 'off',
      'no-constant-condition': 'off',
      'no-prototype-builtins': 'off',
    },
  },
];
