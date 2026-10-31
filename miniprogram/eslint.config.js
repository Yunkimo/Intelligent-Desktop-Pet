// 合并 C3 订阅回归与 C4 WebSocket 适配层的检查配置。
module.exports = [
  { ignores: ['node_modules/**'] },
  {
    files: ['**/*.js'],
    languageOptions: {
      ecmaVersion: 2022,
      sourceType: 'commonjs',
      globals: Object.fromEntries(
        [
          'wx',
          'App',
          'Page',
          'getApp',
          'console',
          'setTimeout',
          'clearTimeout',
          'setInterval',
          'clearInterval',
          'fetch',
          'URL',
          'WebSocket',
          'process',
          '__dirname',
          'Buffer',
          'FormData',
          'Blob',
        ].map((name) => [name, 'readonly'])
      ),
    },
    rules: {
      'no-undef': 'error',
      'no-unused-vars': ['error', { argsIgnorePattern: '^_', caughtErrors: 'none' }],
      'no-unreachable': 'error',
      'no-dupe-keys': 'error',
      'no-func-assign': 'error',
    },
  },
];
