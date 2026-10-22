import AxeBuilder from '@axe-core/playwright';
import { expect, test, type Page } from '@playwright/test';
import type { Result } from 'axe-core';

/** Что блокирует тест. Остальное попадает в отчёт как заметка, но тест не валит (70-07) */
const BLOCKING = new Set(['critical']);

/** Нарушения читаемым списком: правило, насколько серьёзно, что это значит и где именно */
export function formatViolations(violations: readonly Result[]): string {
  return violations
    .map((v) => {
      const nodes = v.nodes
        .slice(0, 5)
        .map(
          (n) =>
            `    - ${n.target.join(' ')}\n      ${n.failureSummary?.replace(/\n/g, '\n      ') ?? ''}`,
        )
        .join('\n');
      return `[${v.impact ?? 'n/a'}] ${v.id}: ${v.help}\n  ${v.helpUrl}\n${nodes}`;
    })
    .join('\n\n');
}

/**
 * Проверка доступности текущего экрана: контраст, подписи, роли, порядок фокуса.
 * Критические нарушения валят тест; остальные уходят в аннотации теста и в консоль.
 * `screen` — название экрана для сообщения.
 */
export async function checkAccessibility(page: Page, screen: string): Promise<void> {
  const { violations } = await new AxeBuilder({ page })
    .withTags(['wcag2a', 'wcag2aa', 'wcag21a', 'wcag21aa'])
    .analyze();

  const blocking = violations.filter((v) => BLOCKING.has(v.impact ?? ''));
  const rest = violations.filter((v) => !BLOCKING.has(v.impact ?? ''));

  if (rest.length > 0) {
    const text = formatViolations(rest);
    test.info().annotations.push({ type: `axe: ${screen}`, description: text });
    console.warn(`axe, экран «${screen}»: нарушения не критические\n${text}`);
  }
  expect(
    blocking,
    `axe, экран «${screen}»: критические нарушения\n${formatViolations(blocking)}`,
  ).toEqual([]);
}
