import { expect, test } from './fixtures';
import { checkAccessibility } from './support/axe';
import {
  applicationForm,
  applicationPage,
  consents,
  companyProfile,
  contractTexts,
  decision,
  fill,
  forbiddenClientWords,
  loansTexts,
  money,
  shell,
  timelineSteps,
  wizard,
  wizardResult,
} from './support/text';
import {
  DECISION_TIMEOUT_MS,
  DISBURSEMENT_TIMEOUT_MS,
  expectNoReload,
  markPageSession,
  waitForStatus,
} from './support/waits';

// Оракул 30-17: ставка 21,5%, платёж 46 677 ₽ (проверено и по API, api/tests/personas)
const AMOUNT = 500_000;
const TERM_MONTHS = 12;
const RATE = '21,5%';
const PAYMENT = 46_677;
const OVERPAYMENT = 60_126;
const TOTAL = AMOUNT + OVERPAYMENT;

test('TS-001: Соколова проходит путь от входа до «Мои кредиты» без перезагрузки страницы', async ({
  clientPage: page,
}) => {
  // Метку ставим после входа и дальше ходим только по ссылкам и кнопкам: страница не перезагружается
  await markPageSession(page);

  await test.step('Главная: «Подобрать кредит»', async () => {
    await checkAccessibility(page, 'Главная');
    await page.getByRole('link', { name: shell.nav.wizard }).first().click();
    await expect(page).toHaveURL(/\/wizard$/);
  });

  await test.step('Мастер: оборудование, 500 000 ₽, 12 месяцев', async () => {
    await expect(page.getByRole('heading', { level: 1, name: wizard.purpose.title })).toBeVisible();
    await page.getByRole('button', { name: wizard.purpose.options.EQUIPMENT.title }).click();
    await page.getByLabel(wizard.amount.label).fill(String(AMOUNT));
    await page.getByRole('button', { name: wizard.amount.next }).click();
    await page.getByRole('button', { name: /12 месяцев/ }).click();

    await expect(page.getByRole('heading', { level: 1, name: wizardResult.title })).toBeVisible();
    await checkAccessibility(page, 'Результат подбора');
    await page.getByRole('button', { name: wizardResult.apply }).first().click();
  });

  await test.step('Заявка: условия, карточка компании и источник данных', async () => {
    await expect(page).toHaveURL(/\/applications\/[^/]+\/edit\/1$/);
    await expect(page.getByLabel(applicationForm.conditions.amount)).toHaveValue(
      /500[\s\u00a0\u202f]?000/,
    );
    await page.getByRole('button', { name: applicationForm.next }).click();
    await expect(page.getByLabel(companyProfile.labels.inn, { exact: true })).toHaveValue(
      '001234567887',
    );
    await expect(page.getByLabel(companyProfile.labels.name, { exact: true })).toHaveValue(
      'Соколова Анна Сергеевна',
    );
    const source = page.getByRole('button', {
      name: fill(companyProfile.source, { field: companyProfile.labels.name }),
    });
    await source.focus();
    await page.keyboard.press('Enter');
    const details = page.getByRole('dialog');
    await expect(details).toBeVisible();
    // Контраст проверяем после fade-in: полупрозрачный кадр ещё смешивает текст с фоном.
    await expect(details).toHaveCSS('opacity', '1');
    await expect(details).toContainText(companyProfile.sourceNames.registry);
    await expect(details).toContainText('Получено');
    await checkAccessibility(page, 'Данные компании и источник');
    await page.keyboard.press('Escape');
    await expect(details).not.toBeVisible();
    await page.getByRole('button', { name: applicationForm.next }).click();
    await page.getByRole('button', { name: applicationForm.next }).click();
  });

  await test.step('Согласия: отмечаем все, принимаем правила простой подписи, подписываем кодом', async () => {
    await expect(page).toHaveURL(/\/edit\/4$/);
    // Согласия приходят с сервера: сколько их у компании, столько галочек и отмечаем
    const agreements = page.getByRole('checkbox', {
      name: fill(consents.agree, { kind: '' }).trim(),
    });
    await expect(agreements.first()).toBeVisible();
    for (const box of await agreements.all()) await box.check();
    await page.getByRole('checkbox', { name: consents.pepAccept }).check();
    await checkAccessibility(page, 'Согласия');
    await page.getByRole('button', { name: consents.requestCode }).click();

    const demo = page.getByText(new RegExp(fill(consents.demoCode, { code: '\\d{6}' })));
    await expect(demo).toBeVisible();
    const code = /\d{6}/.exec((await demo.textContent()) ?? '')?.[0] ?? '';
    await page.getByLabel(consents.codeLabel).fill(code);
    await page.getByRole('button', { name: consents.sign }).click();
    await expect(page.getByText(consents.allSigned)).toBeVisible();
    await page.getByRole('button', { name: applicationForm.next }).click();
  });

  await test.step('Отправка заявки', async () => {
    await expect(page).toHaveURL(/\/edit\/5$/);
    await page.getByRole('button', { name: applicationForm.review.submit }).click();
    await expect(page).toHaveURL(/\/applications\/[^/]+$/);
    // Таймлайн идёт сам: шаги этапов видны сразу после отправки
    const timeline = page.getByRole('list', { name: applicationPage.timelineLabel });
    await expect(timeline).toBeVisible();
    await expect(page.getByText(applicationPage.autoUpdate)).toBeVisible();
    for (const step of timelineSteps) await expect(timeline).toContainText(step.title);
  });

  await test.step('Решение приходит само: «Одобрено», 21,5%, 46 677 ₽', async () => {
    await waitForStatus(
      page,
      page.getByText(applicationPage.decisionDone.approved, { exact: true }).first(),
      'Одобрено',
      DECISION_TIMEOUT_MS,
    );
    const main = page.locator('main');
    await expect(main).toContainText(RATE);
    await expect(main).toContainText(money(PAYMENT));
    await expect(main).toContainText(money(OVERPAYMENT));
    await expect(main).toContainText(money(AMOUNT));
    await expect(main.getByText(decision.rate, { exact: true })).toBeVisible();

    // Клиент не видит баллов и внутренних слов (60-06)
    const text = await main.innerText();
    expect(text).not.toMatch(/\bscore\b|балл/i);
    for (const { label, pattern } of forbiddenClientWords) {
      expect(text, `на экране решения внутреннее слово «${label}»`).not.toMatch(pattern);
    }
    await checkAccessibility(page, 'Решение «Одобрено»');
    await expectNoReload(page);
  });

  await test.step('Принятие и подпись договора кодом', async () => {
    await page.getByRole('button', { name: contractTexts.accept }).click();
    await expect(page.getByRole('heading', { name: contractTexts.heading })).toBeVisible();
    await page.getByRole('checkbox', { name: contractTexts.agree }).check();
    const pep = page.getByRole('checkbox', { name: contractTexts.acceptPep });
    if (await pep.isVisible()) await pep.check();
    await checkAccessibility(page, 'Подписание договора');
    await page.getByRole('button', { name: contractTexts.requestCode }).click();

    const demo = page.getByText(new RegExp(fill(contractTexts.demoCode, { code: '\\d{6}' })));
    await expect(demo).toBeVisible();
    const code = /\d{6}/.exec((await demo.textContent()) ?? '')?.[0] ?? '';
    await page.getByLabel(contractTexts.code).fill(code);
    await page.getByRole('button', { name: contractTexts.sign }).click();
  });

  await test.step('Деньги зачислены: 500 000 ₽', async () => {
    await waitForStatus(
      page,
      page.getByText(contractTexts.issued, { exact: true }),
      'Деньги зачислены',
      DISBURSEMENT_TIMEOUT_MS,
    );
    await expect(page.locator('main')).toContainText(money(AMOUNT));
    await expectNoReload(page);
  });

  await test.step('«Мои кредиты»: кредит и график из 12 платежей', async () => {
    await page.getByRole('link', { name: contractTexts.openLoans }).click();
    await expect(page).toHaveURL(/\/loans$/);
    await expect(page.getByRole('heading', { level: 1, name: loansTexts.title })).toBeVisible();
    await page.getByRole('link', { name: loansTexts.card.open }).first().click();

    const schedule = page.getByRole('table');
    const rows = schedule.locator('tbody tr');
    await expect(rows).toHaveCount(TERM_MONTHS);
    await expect(schedule.locator('tfoot')).toContainText(loansTexts.detail.total);
    await expect(schedule.locator('tfoot')).toContainText(money(TOTAL));
    await checkAccessibility(page, 'Кредит и график');
    await expectNoReload(page);
  });
});
