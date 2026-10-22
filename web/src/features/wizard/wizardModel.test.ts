import { describe, expect, it } from 'vitest';
import {
  isResultLocationState,
  isWizardLocationState,
  paymentOptionsOf,
  previewAnswers,
  relevantAnswers,
  stepsFor,
  totalSteps,
} from './wizardModel';
import { defaultOptions, makeRecommended, makeWizardResult } from '@/test/wizardFactory';

describe('ход мастера: какие вопросы задаём', () => {
  it.each([
    ['EQUIPMENT', ['purpose', 'amount']],
    ['GOODS', ['purpose', 'frequency', 'payback', 'amount']],
    ['ORDER', ['purpose', 'frequency', 'payback', 'govContract', 'amount']],
    ['GAP', ['purpose', 'frequency', 'payback', 'amount']],
    ['GROWTH', ['purpose', 'payback', 'amount']],
    ['OTHER', ['purpose', 'amount']],
    ['UNKNOWN', ['purpose', 'amount']],
  ] as const)('цель %s: до суммы вопросы %j', (purpose, expected) => {
    expect(stepsFor({ purpose }, null)).toEqual(expected);
  });

  it('до ответа на «на что деньги» остаются цель и сумма', () => {
    expect(stepsFor({}, null)).toEqual(['purpose', 'amount']);
  });

  it('платёж и залог появляются только по расчёту бэкенда', () => {
    const answers = { purpose: 'EQUIPMENT' } as const;
    const bare = makeWizardResult({
      primary: makeRecommended({ comfortableOptions: [] }),
      askCollateral: false,
    });
    const withPayment = makeWizardResult({
      primary: makeRecommended({ comfortableOptions: defaultOptions }),
    });
    const withBoth = makeWizardResult({
      primary: makeRecommended({ comfortableOptions: defaultOptions }),
      askCollateral: true,
    });
    const collateralOnly = makeWizardResult({
      primary: makeRecommended({ comfortableOptions: [] }),
      askCollateral: true,
    });
    expect(stepsFor(answers, bare)).toEqual(['purpose', 'amount']);
    expect(stepsFor(answers, withPayment)).toEqual(['purpose', 'amount', 'payment']);
    expect(stepsFor(answers, withBoth)).toEqual(['purpose', 'amount', 'payment', 'collateral']);
    expect(stepsFor(answers, collateralOnly)).toEqual(['purpose', 'amount', 'collateral']);
    expect(paymentOptionsOf(null)).toEqual([]);
    expect(paymentOptionsOf(withPayment)).toHaveLength(3);
  });

  it('всего шагов: пока расчёта нет, платёж и залог считаем впереди', () => {
    expect(totalSteps({ purpose: 'ORDER' }, null)).toBe(7);
    const done = makeWizardResult({ primary: makeRecommended({ comfortableOptions: [] }) });
    expect(totalSteps({ purpose: 'ORDER' }, done)).toBe(5);
  });

  it('устаревшие ответы в запрос не попадают, «Не знаю» сохраняется', () => {
    const answers = {
      purpose: 'EQUIPMENT',
      frequency: 'REGULAR',
      paybackHorizon: 'DAYS',
      govContract: 'YES',
      amountRub: null,
      termMonths: 24,
      collateral: 'NONE',
    } as const;
    expect(previewAnswers(answers)).toEqual({ purpose: 'EQUIPMENT', amountRub: null });
    expect(relevantAnswers(answers, ['purpose', 'amount', 'payment', 'collateral'])).toEqual({
      purpose: 'EQUIPMENT',
      amountRub: null,
      termMonths: 24,
      collateral: 'NONE',
    });
  });

  it('разбор состояния адреса: чужое и пустое отбрасывается', () => {
    expect(isWizardLocationState(null)).toBe(false);
    expect(isWizardLocationState({})).toBe(false);
    expect(isWizardLocationState({ answers: {}, applicationId: null })).toBe(true);
    expect(isResultLocationState({ answers: {}, applicationId: null })).toBe(false);
    expect(
      isResultLocationState({ answers: {}, applicationId: null, result: makeWizardResult() }),
    ).toBe(true);
  });
});
