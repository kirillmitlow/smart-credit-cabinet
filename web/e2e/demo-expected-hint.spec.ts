import { test, expect } from './fixtures';
import { submitApplicationRequest } from './support/bank-case';
import { checkAccessibility } from './support/axe';
import type { Persona } from '../src/api/generated/model';
import { demo as t } from '../src/texts/demo';
import { outcome } from '../src/features/demo/formatting';

for (const changed of [false, true]) {
  test(`T-436: ожидаемый исход ${changed ? 'скрыт после изменения суммы' : 'закрыт до раскрытия'}`, async ({
    clientPage: page,
  }) => {
    const response = await page.request.get('/api/demo/personas');
    expect(response.status()).toBe(200);
    const personas = (await response.json()) as Persona[];
    const persona = personas.find((p) => p.code === 'sokolova');
    const request = persona?.application;
    if (!persona || !request?.productCode || !request.termMonths)
      throw new Error('Original persona request missing');
    const loaded = page.waitForResponse(
      (r) => r.url().endsWith('/api/demo/personas') && r.request().method() === 'GET',
    );
    const id = await submitApplicationRequest(page, {
      productCode: request.productCode,
      amountRub: Number(request.amountRub) + (changed ? 1000 : 0),
      termMonths: request.termMonths,
      purposeCode: 'EQUIPMENT',
    });
    await expect(page).toHaveURL(new RegExp(`/applications/${id}$`));
    expect((await loaded).status()).toBe(200);
    const hint = page.getByTestId('demo-expected-hint');
    if (changed) {
      await expect(page.getByRole('heading', { level: 1 })).toContainText('Заявка');
      await expect(hint).toHaveCount(0);
    } else {
      await expect(hint).toBeVisible();
      const control = hint.getByRole('button', { name: t.hint });
      await expect(control).toHaveAttribute('aria-expanded', 'false');
      await expect(hint.getByText(t.hintHelp)).not.toBeVisible();
      await control.click();
      await expect(hint.getByText(t.hintHelp)).toBeVisible();
      await expect(hint).toContainText(persona.title);
      await expect(hint).toContainText(outcome(persona.expectedOutcome));
      await checkAccessibility(page, 'подсказка исхода демо-персоны');
      await control.click();
      await expect(control).toHaveAttribute('aria-expanded', 'false');
    }
  });
}
