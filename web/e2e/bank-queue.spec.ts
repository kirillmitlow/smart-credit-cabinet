import { test, expect } from './fixtures';
import { checkAccessibility } from './support/axe';
import { submitInvestmentReview } from './support/bank-case';
import { expectNoReload, markPageSession } from './support/waits';
import { bankWorkspace as t } from '../src/texts/bank';

test('TS-030: ручная заявка появляется в банковской очереди без перезагрузки', async ({
  sessions,
}) => {
  const client = sessions.client;
  const bank = await sessions.bank();
  await markPageSession(bank);

  const id = await submitInvestmentReview(client);
  const row = bank.getByTestId(`bank-queue-${id}`);
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
