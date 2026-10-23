import { expect, type Page } from '@playwright/test';
import { applicationForm, consents, fill } from './text';

interface ApplicationRequest {
  productCode: string;
  amountRub: number;
  termMonths: number;
  purposeCode: string;
}

export function submitInvestmentReview(client: Page): Promise<string> {
  return submitApplicationRequest(
    client,
    {
      productCode: 'INVESTMENT',
      amountRub: 1_000_000,
      termMonths: 60,
      purposeCode: 'EQUIPMENT',
    },
    { collateral: { description: 'Кофейное оборудование', valueRub: 1_500_000 } },
  );
}

export async function submitApplicationRequest(
  client: Page,
  request: ApplicationRequest,
  answers?: Record<string, unknown>,
): Promise<string> {
  // Подготавливаем запрос через публичный API. Вход, согласия и отправка — через интерфейс.
  const created = await client.request.post('/api/v1/applications', { data: request });
  expect(created.status()).toBe(201);
  const application = (await created.json()) as { id: string; version: number };
  if (answers) {
    const draft = await client.request.patch(`/api/v1/applications/${application.id}/draft`, {
      data: { version: application.version, answers },
    });
    expect(draft.status()).toBe(200);
  }
  await client.goto(`/applications/${application.id}/edit/4`);
  const agreements = client.getByRole('checkbox', {
    name: fill(consents.agree, { kind: '' }).trim(),
  });
  await expect(agreements.first()).toBeVisible();
  for (const agreement of await agreements.all()) await agreement.check();
  const pep = client.getByRole('checkbox', { name: consents.pepAccept });
  if (await pep.isVisible()) await pep.check();
  await client.getByRole('button', { name: consents.requestCode }).click();
  const demo = client.getByText(new RegExp(fill(consents.demoCode, { code: '\\d{6}' })));
  await expect(demo).toBeVisible();
  const code = /\d{6}/.exec((await demo.textContent()) ?? '')?.[0];
  if (!code) throw new Error('Код согласия не показан в деморежиме');
  await client.getByLabel(consents.codeLabel).fill(code);
  await client.getByRole('button', { name: consents.sign }).click();
  await expect(client.getByText(consents.allSigned)).toBeVisible();
  await client.getByRole('button', { name: applicationForm.next }).click();
  await client.getByRole('button', { name: applicationForm.review.submit }).click();

  return application.id;
}
