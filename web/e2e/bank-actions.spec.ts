import { expect, test } from './fixtures';
import { checkAccessibility } from './support/axe';
import { submitApplicationRequest } from './support/bank-case';
import { expectNoReload, markPageSession } from './support/waits';
import { bankActions as t } from '../src/texts/bankActions';
import { clientTasks, fill, outcomes } from '../src/texts';

test.use({ persona: { code: 'stankoprom', inn: '0017654322', personName: 'Кузнецов' } });

// Текстовое пояснение проверяет T-432 независимо от ещё не готового файлового пути T-442.
test('TS-032: Станкопром отвечает банку, сотрудник одобряет, клиент видит результат', async ({
  sessions,
}) => {
  const client = sessions.client;
  const bank = await sessions.bank();
  const id = await submitApplicationRequest(
    client,
    {
      productCode: 'INVESTMENT',
      amountRub: 15_000_000,
      termMonths: 60,
      purposeCode: 'EQUIPMENT',
    },
    { collateral: { description: 'Покупаемая линия', valueRub: 25_000_000 } },
  );
  await markPageSession(client);
  await expect(client.getByRole('heading', { name: outcomes.manual.title })).toBeVisible({
    timeout: 90_000,
  });
  const row = bank.getByTestId(`bank-queue-${id}`);
  await expect(row).toBeVisible({ timeout: 90_000 });
  await row.getByRole('link').click();
  await bank.getByRole('button', { name: t.info, exact: true }).click();
  const dialog = bank.getByRole('dialog');
  const taskTitle = 'Поясните сроки поставки линии';
  const answer = 'Поставка подтверждена поставщиком, оплата после монтажа линии';
  await dialog.getByLabel(t.taskTitle, { exact: false }).fill(taskTitle);
  await dialog
    .getByLabel(t.why, { exact: false })
    .fill('Нужно проверить план приобретения оборудования');
  await checkAccessibility(bank, 'Запрос пояснения сотрудником');
  await bank.screenshot({ path: test.info().outputPath('bank-information-request.png') });
  await dialog.getByRole('button', { name: t.confirm }).click();
  await expect(bank.getByText(t.requested)).toBeVisible();
  await expect(client.getByRole('heading', { name: taskTitle })).toBeVisible({ timeout: 90_000 });
  await client.getByLabel(fill(clientTasks.answerLabel, { title: taskTitle })).fill(answer);
  await client.getByRole('button', { name: clientTasks.submit, exact: true }).click();
  await expect(client.getByRole('heading', { name: outcomes.manual.title })).toBeVisible({
    timeout: 90_000,
  });
  await expect(row).toBeVisible({ timeout: 90_000 });
  await row.getByRole('link').click();
  const requests = bank.getByTestId('bank-client-requests');
  await expect(requests).toContainText(answer);
  await expect(requests).toContainText(fill(t.newAnswer, { round: 1 }));
  await bank.screenshot({ path: test.info().outputPath('bank-client-answer.png') });
  await bank.getByRole('button', { name: t.approve, exact: true }).click();
  await expect(dialog.getByText(t.agreement)).toBeVisible();
  await dialog.getByRole('button', { name: t.confirm }).click();
  await expect(bank.getByText(t.saved)).toBeVisible();
  await expect(client.getByRole('heading', { name: /^Одобрено/ })).toBeVisible({ timeout: 90_000 });
  await checkAccessibility(client, 'Клиент после решения сотрудника');
  await expectNoReload(client);
  const decision = await client.request.get(`/api/v1/applications/${id}/decision`);
  expect(decision.status()).toBe(200);
  const body = (await decision.json()) as Record<string, unknown>;
  expect(body.outcome).toBe('APPROVED');
  expect(body).not.toHaveProperty('score');
  expect(body).not.toHaveProperty('dscr');
  expect(body).not.toHaveProperty('overrideReason');
});
