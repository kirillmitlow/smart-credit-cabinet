import { expect, test } from './fixtures';
import { checkAccessibility } from './support/axe';
import { submitApplicationRequest } from './support/bank-case';
import { expectNoReload, markPageSession } from './support/waits';
import { applicationPage, contractTexts, fill, money } from './support/text';
import { bankActions as t, bankManual as m } from '../src/texts/bankActions';
import { counterOffer } from '../src/texts/counterOffer';

test.use({ persona: { code: 'stankoprom', inn: '0017654322', personName: 'Кузнецов' } });

test('TS-035: ручное встречное Станкопрома проходит от расчёта до выдачи', async ({ sessions }) => {
  const client = sessions.client;
  const bank = await sessions.bank();
  const id = await submitApplicationRequest(
    client,
    { productCode: 'INVESTMENT', amountRub: 15_000_000, termMonths: 60, purposeCode: 'EQUIPMENT' },
    { collateral: { description: 'Покупаемая линия', valueRub: 25_000_000 } },
  );
  const row = bank.getByTestId(`bank-queue-${id}`);
  await expect(row).toBeVisible({ timeout: 90_000 });
  await row.getByRole('link').click();
  const before = (await (
    await bank.request.get(`/api/v1/backoffice/applications/${id}`)
  ).json()) as { version: number; decisions: unknown[] };
  await bank.getByRole('button', { name: t.manual }).click();
  const dialog = bank.getByRole('dialog');
  await dialog.getByLabel(m.amount).fill('10000000');
  await dialog.getByLabel(m.rate, { exact: true }).fill('19.5');
  await dialog.getByLabel(t.reason).selectOption('UW_RISK_HIGHER');
  const comment =
    'Внутренняя оценка: по результатам проверки документов уменьшаем сумму финансирования.';
  await dialog.getByLabel(t.comment).fill(comment);
  await expect(dialog.getByRole('button', { name: m.save })).toBeDisabled();
  await dialog.getByRole('button', { name: m.calculate }).click();
  await expect(dialog.getByText(m.allowed)).toBeVisible();
  await expect(dialog.getByTestId('bank-manual-result')).toContainText(money(262_164));
  const after = (await (
    await bank.request.get(`/api/v1/backoffice/applications/${id}`)
  ).json()) as { version: number; decisions: unknown[]; status: string };
  expect(after.version).toBe(before.version);
  expect(after.decisions).toHaveLength(before.decisions.length);
  expect(after.status).toBe('MANUAL_REVIEW');
  await expect(dialog).toHaveCSS('opacity', '1');
  await checkAccessibility(bank, 'Расчёт ручного встречного');
  await bank.screenshot({ path: test.info().outputPath('manual-offer-preview.png') });
  await markPageSession(client);
  await dialog.getByRole('button', { name: m.save }).click();
  await expect(bank.getByText(t.saved)).toBeVisible();
  await expect(client.getByRole('button', { name: counterOffer.choose })).toBeVisible({
    timeout: 90_000,
  });
  await expect(client.locator('main')).not.toContainText(comment);
  await client.getByRole('button', { name: counterOffer.choose }).click();
  await expect(client.getByRole('heading', { name: contractTexts.heading })).toBeVisible();
  await client.getByRole('checkbox', { name: contractTexts.agree }).check();
  const pep = client.getByRole('checkbox', { name: contractTexts.acceptPep });
  if (await pep.isVisible()) await pep.check();
  await client.getByRole('button', { name: contractTexts.requestCode }).click();
  const codeLine = client.getByText(new RegExp(fill(contractTexts.demoCode, { code: '\\d{6}' })));
  await expect(codeLine).toBeVisible();
  const code = /\d{6}/.exec(await codeLine.innerText())?.[0];
  expect(code).toBeTruthy();
  await client.getByLabel(contractTexts.code).fill(code!);
  await client.getByRole('button', { name: contractTexts.sign }).click();
  await expect(
    client.getByText(fill(applicationPage.moneyDone, { amount: '' }).trim()).first(),
  ).toBeVisible({ timeout: 60_000 });
  await expect(client.locator('main')).toContainText(money(10_000_000));
  await expectNoReload(client);
});
