import { axe } from 'vitest-axe';

const BLOCKING_IMPACTS = new Set(['critical', 'serious']);

/**
 * Доступность в экранных тестах (D-089, 70-07): нарушения уровня «критично» и «серьёзно» роняют тест,
 * остальное не мешает. Контраст в jsdom не считается (нет раскладки): его проверяют тест темы и Playwright.
 */
export async function blockingA11yViolations(container: Element): Promise<string[]> {
  const results = await axe(container, { rules: { 'color-contrast': { enabled: false } } });
  return results.violations
    .filter((violation) => violation.impact && BLOCKING_IMPACTS.has(violation.impact))
    .map(
      (violation) =>
        `${violation.id} (${violation.impact}): ${violation.help} — ${violation.nodes
          .map((node) => node.target.join(' '))
          .join('; ')}`,
    );
}
