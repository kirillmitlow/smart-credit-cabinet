import { describe, expect, it } from 'vitest';
import { bankPalette, brandPalette, theme, tokens } from './theme';

/** Контраст по WCAG 2.1: jsdom цвет не считает, поэтому пары цветов темы проверяем расчётом (T-400) */
function luminance(hex: string): number {
  const channels = [1, 3, 5].map((start) => parseInt(hex.slice(start, start + 2), 16) / 255);
  const [r, g, b] = channels.map((c) => (c <= 0.03928 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4));
  return 0.2126 * r! + 0.7152 * g! + 0.0722 * b!;
}

export function contrast(foreground: string, background: string): number {
  const [light, dark] = [luminance(foreground), luminance(background)].sort((a, b) => b - a);
  return (light! + 0.05) / (dark! + 0.05);
}

const AA = 4.5;

describe('контраст темы (WCAG AA, 4,5:1)', () => {
  const primary = brandPalette[theme.primaryShade as number]!;

  it('белый текст на красной кнопке', () => {
    expect(contrast('#ffffff', primary)).toBeGreaterThanOrEqual(AA);
  });

  it('красная ссылка на белом фоне', () => {
    expect(contrast(primary, '#ffffff')).toBeGreaterThanOrEqual(AA);
  });

  it('демо-плашка: тёмно-красный текст на светло-красном фоне', () => {
    expect(contrast(tokens.demoBanner.color, tokens.demoBanner.background)).toBeGreaterThanOrEqual(
      AA,
    );
  });

  it('полоса зоны банка: белый текст на синем', () => {
    expect(contrast(tokens.bankStrip.color, tokens.bankStrip.background)).toBeGreaterThanOrEqual(
      AA,
    );
  });

  it('полоса демо: белый текст на тёмно-сером', () => {
    expect(contrast(tokens.demoStrip.color, tokens.demoStrip.background)).toBeGreaterThanOrEqual(
      AA,
    );
  });

  it('приглушённый текст на белом', () => {
    expect(contrast(tokens.dimmedText, '#ffffff')).toBeGreaterThanOrEqual(AA);
  });
});

describe('тема', () => {
  it('основной цвет красный, банк — другой', () => {
    expect(theme.primaryColor).toBe('brand');
    expect(brandPalette).toHaveLength(10);
    expect(bankPalette).toHaveLength(10);
    expect(tokens.bankStrip.background).not.toBe(tokens.demoBanner.background);
  });

  it('шрифт подключён локально (без CDN)', () => {
    expect(theme.fontFamily).toContain('Inter Variable');
  });
});
