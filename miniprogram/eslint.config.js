module.exports = [
  {
    files: ['**/*.js'],
    ignores: ['node_modules/**'],
    languageOptions: {
      ecmaVersion: 2022,
      sourceType: 'commonjs',
      globals: Object.fromEntries(
        [
          'wx',
          'Page',
          'getApp',
          'console',
          'setTimeout',
          'clearTimeout',
          'fetch',
          'URL',
          'WebSocket',
          'process',
          '__dirname',
        ].map((name) => [name, 'readonly'])
      ),
    },
    rules: {
      'no-undef': 'error',
      'no-unused-vars': ['error', { argsIgnorePattern: '^_', caughtErrors: 'none' }],
    },
  },
];
