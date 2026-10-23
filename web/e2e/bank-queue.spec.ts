import { test, expect } from './fixtures';
import { checkAccessibility } from './support/axe';
import { applicationForm, consents, fill } from './support/text';
import { expectNoReload, markPageSession } from './support/waits';
import { bankWorkspace as t } from '../src/texts/bank';

test('TS-030: ручная заявка появляется в банковской очереди без перезагрузки', async ({
  sessions,
}) => {
  const client = sessions.client;
  const bank = await sessions.bank();
  await markPageSession(bank);

  // Подготавливаем только запрос клиента через публичный API: клиентские экраны — зона A.
  // Вход обеих сторон, согласия и отправка проходят через интерфейс.
  const created = await client.request.post('/api/v1/applications', {
    data: {
      productCode: 'INVESTMENT',
      amountRub: 1_000_000,
      termMonths: 60,
      purposeCode: 'EQUIPMENT',
    },
  });
  expect(created.status()).toBe(201);
  const application = (await created.json()) as { id: string; version: number };
  const draft = await client.request.patch(`/api/v1/applications/${application.id}/draft`, {
    data: {
      version: application.version,
      answers: { collateral: { description: 'Кофейное оборудование', valueRub: 1_500_000 } },
    },
  });
  expect(draft.status()).toBe(200);
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

  const row = bank.getByTestId(`bank-queue-${application.id}`);
  await expect(row).toBeVisible({ timeout: 90_000 });
  await expect(row).toContainText('Инвестиционный кредит');
  await expect(row).toContainText('Нужно оценить залог');
  await expect(row).toContainText(t.client);
  await expect(row).toContainText(t.hints.REQUEST_SELLER_DOCUMENT);
  await expectNoReload(bank);
  await checkAccessibility(bank, 'Банковская очередь');
  await bank.getByRole('combobox', { name: t.productFilter }).click();
  await bank.getByRole('option', { name: 'Кредитная линия', exact: true }).click();
  await expect(bank.getByText(t.emptyFilter)).toBeVisible();
  await bank.getByRole('combobox', { name: t.productFilter }).click();
  await bank.getByRole('option', { name: 'Инвестиционный кредит', exact: true }).click();
  await expect(row).toBeVisible();
  await bank.screenshot({ path: test.info().outputPath('bank-queue.png'), fullPage: true });
});
