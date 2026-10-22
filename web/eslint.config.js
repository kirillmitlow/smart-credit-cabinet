import js from '@eslint/js';
import globals from 'globals';
import jsxA11y from 'eslint-plugin-jsx-a11y';
import reactHooks from 'eslint-plugin-react-hooks';
import reactRefresh from 'eslint-plugin-react-refresh';
import tseslint from 'typescript-eslint';

export default tseslint.config(
  { ignores: ['dist', 'coverage', 'node_modules', 'src/api/generated'] },
  js.configs.recommended,
  ...tseslint.configs.recommendedTypeChecked.map((config) => ({
    ...config,
    files: ['**/*.{ts,tsx}'],
  })),
  jsxA11y.flatConfigs.recommended,
  reactHooks.configs.flat.recommended,
  {
    files: ['**/*.{ts,tsx}'],
    languageOptions: {
      ecmaVersion: 2023,
      globals: globals.browser,
      parserOptions: {
        projectService: true,
        tsconfigRootDir: import.meta.dirname,
      },
    },
    plugins: { 'react-refresh': reactRefresh },
    linterOptions: { reportUnusedDisableDirectives: 'error' },
    rules: {
      'react-refresh/only-export-components': ['error', { allowConstantExport: true }],
      // any допустим только с комментарием-причиной: // eslint-disable-next-line ... -- причина
      '@typescript-eslint/no-explicit-any': 'error',
      '@typescript-eslint/ban-ts-comment': [
        'error',
        {
          'ts-expect-error': 'allow-with-description',
          'ts-ignore': true,
          minimumDescriptionLength: 10,
        },
      ],
      '@typescript-eslint/consistent-type-imports': 'error',
      '@typescript-eslint/no-floating-promises': 'error',
      // Каждое правило jsx-a11y — ошибка, а не предупреждение (70-07)
      ...Object.fromEntries(
        Object.keys(jsxA11y.flatConfigs.recommended.rules).map((rule) => [rule, 'error']),
      ),
      // Экраны ходят в api только через сгенерированные хуки (D-080)
      'no-restricted-globals': [
        'error',
        {
          name: 'fetch',
          message: 'Запросы только через src/api (сгенерированные хуки).',
        },
        { name: 'XMLHttpRequest', message: 'Запросы только через src/api.' },
      ],
      'no-restricted-properties': [
        'error',
        { object: 'window', property: 'fetch', message: 'Запросы только через src/api.' },
        { object: 'globalThis', property: 'fetch', message: 'Запросы только через src/api.' },
      ],
    },
  },
  {
    // Слой API и тесты — единственные места, где допустим голый fetch
    files: ['src/api/**', 'src/test/**', '**/*.test.{ts,tsx}'],
    rules: { 'no-restricted-globals': 'off', 'no-restricted-properties': 'off' },
  },
  {
    files: ['*.config.{js,ts}', 'scripts/**/*.mjs'],
    languageOptions: { globals: globals.node },
  },
  {
    files: ['**/*.test.{ts,tsx}', 'src/test/**'],
    rules: {
      'react-refresh/only-export-components': 'off',
    },
  },
);
