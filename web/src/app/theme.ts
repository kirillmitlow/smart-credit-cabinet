import {
  Badge,
  Button,
  defaultVariantColorsResolver,
  Card,
  createTheme,
  Input,
  Paper,
  type CSSVariablesResolver,
  type MantineColorsTuple,
  type VariantColorsResolver,
} from '@mantine/core';

/**
 * Единственный файл с дизайн-токенами (T-400). Направление «Контраст», бренд Super-Bank (D-113):
 * графитовая шапка, светло-серый фон, белые карточки без рамок, кнопки-«таблетки», красный акцент.
 * Эталон — макеты в docs/design/super-bank/. Экраны берут цвета и радиусы отсюда.
 */

/** Красный акцент. Белый текст на оттенке 6 даёт контраст не ниже 4,5:1 (проверяет theme.test.ts) */
const brand: MantineColorsTuple = [
  '#fdecec',
  '#f9d3d4',
  '#f2a7a9',
  '#ec7a7e',
  '#e65358',
  '#e0393f',
  '#d7262e',
  '#b8141b',
  '#9a1117',
  '#7d0d12',
];

/** Графит: шапка, тёмные карточки, вторичные кнопки */
const graphite: MantineColorsTuple = [
  '#f6f6f7',
  '#eeeef0',
  '#e4e4e7',
  '#d4d4d8',
  '#a1a1aa',
  '#71717a',
  '#52525b',
  '#3f3f46',
  '#27272a',
  '#17171a',
];

/** Цвет зоны банка: холодный, чтобы зону нельзя было спутать с клиентской (D-010, D-085) */
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
  /** Фон страницы: карточки на нём белые */
  pageBackground: graphite[1],
  /** Шапка и тёмные блоки */
  header: { background: graphite[9], color: '#ffffff', muted: '#b4b4bb', border: graphite[6] },
  /** Плашка «Демо-прототип»: светлый текст на почти чёрном и красная метка «ДЕМО» */
  demoBanner: { background: '#0b0b0d', color: graphite[3], badge: brand[6] },
  /** Подпись зоны банка под шапкой */
  bankStrip: { background: bank[8], color: '#ffffff' },
  /** Служебный вид демо-панели */
  demoStrip: { background: graphite[7], color: '#ffffff' },
  /** Приглушённый текст: контраст не ниже 4,5:1 и на белом, и на сером фоне */
  dimmedText: graphite[6],
  /** Светлый акцент на тёмном фоне (сумма в рекомендуемой карточке) */
  accentOnDark: '#ff8a8d',
  /** Метки состояний */
  status: {
    waiting: { background: '#fff1d6', color: '#7a4300' },
    success: { background: '#e6f4ea', color: '#14532d' },
  },
  minWidthPx: 1280,
} as const;

export const fonts = {
  body: '"Onest Variable", system-ui, -apple-system, "Segoe UI", Roboto, Arial, sans-serif',
  display: '"Unbounded Variable", "Onest Variable", system-ui, sans-serif',
} as const;

/**
 * Вариант `light` у основного цвета — серый, а не бледно-розовый (D-113): красным остаётся только
 * главное действие экрана. Остальные цвета и варианты — как в Mantine.
 */
const variantColorResolver: VariantColorsResolver = (input) => {
  const defaults = defaultVariantColorsResolver(input);
  const isPrimary = input.color === undefined || input.color === 'brand';
  if (input.variant === 'light' && isPrimary) {
    return {
      ...defaults,
      background: graphite[1],
      hover: graphite[2],
      color: graphite[9],
      border: 'none',
    };
  }
  return defaults;
};

export const theme = createTheme({
  variantColorResolver,
  primaryColor: 'brand',
  primaryShade: 6,
  colors: { brand, graphite, bank, dark: graphite },
  defaultRadius: 'md',
  radius: { xs: '6px', sm: '8px', md: '12px', lg: '16px', xl: '20px' },
  fontFamily: fonts.body,
  headings: {
    fontFamily: fonts.display,
    fontWeight: '700',
    sizes: {
      h1: { fontSize: '34px', lineHeight: '1.15' },
      h2: { fontSize: '22px', lineHeight: '1.25' },
      h3: { fontSize: '18px', lineHeight: '1.3' },
      h4: { fontSize: '16px', lineHeight: '1.35' },
    },
  },
  focusRing: 'auto',
  white: '#ffffff',
  black: graphite[9],
  components: {
    Button: Button.extend({
      defaultProps: { radius: 'xl' },
      styles: { label: { fontWeight: 600 } },
    }),
    Paper: Paper.extend({ defaultProps: { radius: 'lg' } }),
    /** Метки строчными буквами, как в макете: капслок читается хуже */
    Badge: Badge.extend({
      defaultProps: { radius: 'xl' },
      styles: { root: { textTransform: 'none', fontWeight: 700 } },
    }),
    Card: Card.extend({ defaultProps: { radius: 'lg' } }),
    Input: Input.extend({ defaultProps: { radius: 'md' } }),
  },
});

export const brandPalette = brand;
export const graphitePalette = graphite;
export const bankPalette = bank;

/** Приглушённый текст контрастнее стандартного; рамки карточек светлее — на сером фоне они не нужны */
export const cssVariablesResolver: CSSVariablesResolver = () => ({
  variables: { '--scc-page-bg': tokens.pageBackground },
  light: {
    '--mantine-color-dimmed': tokens.dimmedText,
    '--mantine-color-default-border': graphite[2],
  },
  dark: {},
});
