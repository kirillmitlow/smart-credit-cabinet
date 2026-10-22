import { expect, test } from '@playwright/test';
import { checkAccessibility, formatViolations } from './support/axe';
import { expectNoReload, markPageSession, waitForStatus } from './support/waits';

// Тесты самой обвязки на заглушечных страницах: стенд не нужен (T-518).

test.describe('axe-проверка', () => {
  test('чистая страница проходит', async ({ page }) => {
    await page.setContent(
      '<html lang="ru"><head><title>Заглушка</title></head><body><main><h1>Заголовок</h1><button>Продолжить</button></main></body></html>',
    );
    await checkAccessibility(page, 'Заглушка');
  });

  test('кнопка без названия — критическое нарушение, и оно читается человеком', async ({
    page,
  }) => {
    await page.setContent(
      '<html lang="ru"><head><title>Заглушка</title></head><body><main><h1>Заголовок</h1><button></button></main></body></html>',
    );
    const failure = await checkAccessibility(page, 'Заглушка с кнопкой').then(
      () => null,
      (error: unknown) => (error instanceof Error ? error.message : String(error)),
    );
    expect(failure).toContain('Заглушка с кнопкой');
    expect(failure).toContain('[critical] button-name');
  });

  test('форматирование нарушений: правило, важность и узел', () => {
    const text = formatViolations([
      {
        id: 'color-contrast',
        impact: 'serious',
        help: 'Контраст недостаточен',
        helpUrl: 'https://dequeuniversity.com/rules/axe/4.14/color-contrast',
        nodes: [{ target: ['.btn'], failureSummary: 'Fix any of the following:\n  low contrast' }],
        tags: [],
        description: '',
      } as never,
    ]);
    expect(text).toContain('[serious] color-contrast: Контраст недостаточен');
    expect(text).toContain('- .btn');
  });
});

test.describe('ожидание без перезагрузки', () => {
  test('waitForStatus дожидается элемента, который появляется сам, и метка остаётся на месте', async ({
    page,
  }) => {
    await page.setContent(
      '<main><p id="s">Проверяем</p><script>setTimeout(() => { document.getElementById("s").textContent = "Одобрено"; }, 800);</script></main>',
    );
    await markPageSession(page);
    await waitForStatus(page, page.getByText('Одобрено'), 'Одобрено', 10_000);
    await expectNoReload(page);
  });

  test('перезагрузка стирает метку, и проверка это ловит', async ({ page }) => {
    await page.setContent('<main>страница</main>');
    await markPageSession(page);
    await page.goto('about:blank');
    await expect(expectNoReload(page)).rejects.toThrow(/перезагружалась/);
  });

  test('при таймауте сообщение показывает, что было на экране', async ({ page }) => {
    await page.setContent('<main>Всё ещё проверяем</main>');
    await expect(waitForStatus(page, page.getByText('Одобрено'), 'Одобрено', 500)).rejects.toThrow(
      /На экране: Всё ещё проверяем/,
    );
  });
});
