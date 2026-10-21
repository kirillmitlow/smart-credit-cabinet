import { createTheme, type CSSVariablesResolver, type MantineColorsTuple } from '@mantine/core';

/**
 * Единственный файл с дизайн-токенами (T-400, D-085, D-099): красный акцент, светлая тема,
 * стандартные компоненты Mantine без собственного оформления. Цвета и радиусы берём отсюда,
 * так что смена оформления не требует переписывать экраны.
 */

/** Красный акцент. Белый текст на оттенке 7 даёт контраст не ниже 4,5:1 (проверяет theme.test.ts) */
const brand: MantineColorsTuple = [
  '#fff0ef',
  '#ffdedc',
  '#fdbab5',
  '#fa9189',
  '#f46a5f',
  '#ea4a3d',
  '#d6352a',
  '#c22b21',
  '#a82219',
  '#8c1b14',
];

/** Цвет рабочего места банка: холодный, чтобы зону нельзя было спутать с клиентской (D-010, D-085) */
const bank: MantineColorsTuple = [
  '#eef1fb',
  '#dce2f5',
  '#b6c2ea',
  '#8ea0df',
  '#6d83d6',
  '#566fd1',
  '#4a63cf',
  '#3b53b8',
  '#3248a5',
  '#243a92',
];

export const tokens = {
  /** Плашка «Демо-прототип»: тёмно-красный текст на светло-красном фоне */
  demoBanner: { background: brand[0], color: brand[9] },
  /** Цветная полоса сверху в зоне банка и подпись */
  bankStrip: { background: bank[8], color: '#ffffff' },
  /** Служебный вид демо-панели */
  demoStrip: { background: '#343a40', color: '#ffffff' },
  /** Приглушённый текст: стандартный серый Mantine даёт контраст 3,5:1, нужно не меньше 4,5:1 (WCAG AA) */
  dimmedText: '#5c636a',
  minWidthPx: 1280,
} as const;

export const theme = createTheme({
  primaryColor: 'brand',
  primaryShade: 7,
  colors: { brand, bank },
  defaultRadius: 'md',
  fontFamily:
    '"Inter Variable", system-ui, -apple-system, "Segoe UI", Roboto, "Helvetica Neue", Arial, sans-serif',
  headings: { fontWeight: '600' },
  focusRing: 'auto',
  white: '#ffffff',
  black: '#1a1b1e',
});

export const brandPalette = brand;
export const bankPalette = bank;

/** Переопределяет цвет `c="dimmed"` на более контрастный */
export const cssVariablesResolver: CSSVariablesResolver = () => ({
  variables: {},
  light: { '--mantine-color-dimmed': tokens.dimmedText },
  dark: {},
});
