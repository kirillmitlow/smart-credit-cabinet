import { test, expect } from './fixtures';
import { checkAccessibility } from './support/axe';
import { submitInvestmentReview } from './support/bank-case';
import { money } from './support/text';
import { expectNoReload, markPageSession } from './support/waits';
import { formatPercent } from '../src/lib/format';
import { bankCard as t } from '../src/texts/bank';
import { applicationStatusLabels } from '../src/texts';

test('TS-031: банковская карточка показывает оценку, снимки и историю настоящей заявки', async ({
  sessions,
}) => {
  const bank = await sessions.bank();
  const id = await submitInvestmentReview(sessions.client);
  const row = bank.getByTestId(`bank-queue-${id}`);
  await expect(row).toBeVisible({ timeout: 90_000 });
  await markPageSession(bank);
  await row.getByRole('link').click();
  const moneyPanel = bank.getByTestId('bank-money');
  await expect(moneyPanel).toBeVisible();
  const response = await bank.request.get(`/api/v1/backoffice/applications/${id}`);
  expect(response.status()).toBe(200);
  const data = (await response.json()) as {
    decision: { paymentRub: number; score: number; grade: string; rate: { ratePercent: number } };
    sourceSnapshots: { id: string }[];
  };
  await expect(moneyPanel).toContainText(money(data.decision.paymentRub));
  await expect(bank.getByTestId('bank-rate')).toContainText(
    formatPercent(data.decision.rate.ratePercent),
  );
  await expect(bank.getByTestId('bank-factors')).toContainText(
    `Баллы: ${data.decision.score} из 100`,
  );
  await expect(bank.getByRole('meter')).toHaveCount(9);
  expect(data.sourceSnapshots.length).toBeGreaterThan(0);
  await expect(bank.getByTestId('bank-sources')).toContainText(t.actualAt);
  await expect(bank.getByTestId('bank-sources')).toContainText(t.retrievedAt);
  await expect(bank.getByTestId('bank-history')).toContainText(
    applicationStatusLabels.MANUAL_REVIEW,
  );
  await checkAccessibility(bank, 'Карточка банка');
  for (const block of [
    'bank-factors',
    'bank-money',
    'bank-rate',
    'bank-flags',
    'bank-variants',
    'bank-sources',
    'bank-history',
    'bank-documents',
  ]) {
    await bank.getByTestId(block).screenshot({ path: test.info().outputPath(`${block}.png`) });
  }
  const original = bank.getByTestId('bank-sources').locator('details').first();
  await original.locator('summary').first().click();
  await expect(original).toHaveJSProperty('open', true);
  await bank.getByRole('link', { name: t.back }).click();
  await expect(bank).toHaveURL(/\/bank$/);
  await expectNoReload(bank);
});
