import { describe, expect, it } from 'vitest';
import { applicationStatusLabels } from '@/texts';
import { clientStepOf } from './statuses';
import { buildTimeline } from './timelineModel';

const base = { submittedAt: '2026-10-21T09:04:00Z', amountRub: 500_000 };
const states = (status: string) =>
  buildTimeline({ ...base, status }).steps.map((step) => `${step.key}:${step.state}`);

describe('14 статусов → 6 шагов клиента (20-02)', () => {
  it('каждый статус из словаря обработан', () => {
    for (const status of Object.keys(applicationStatusLabels)) {
      const model = buildTimeline({ ...base, status });
      expect(model.steps.length > 0 || model.note !== null || status === 'DRAFT').toBe(true);
    }
  });

  it.each([
    ['SUBMITTED', ['submitted:running', 'checking:waiting']],
    ['CHECKING', ['submitted:done', 'checking:running', 'evaluating:waiting']],
    ['NEEDS_INFO', ['checking:done', 'needsHelp:running', 'evaluating:waiting']],
    ['MANUAL_REVIEW', ['checking:done', 'evaluating:running', 'decision:waiting']],
    ['APPROVED', ['evaluating:done', 'decision:done', 'signing:waiting']],
    ['COUNTER_OFFER', ['decision:done', 'signing:waiting']],
    ['OFFER_ACCEPTED', ['decision:done', 'signing:running', 'money:waiting']],
    ['SIGNED', ['signing:done', 'money:running']],
    ['DISBURSING', ['signing:done', 'money:running']],
    ['DISBURSED', ['signing:done', 'money:done']],
  ])('%s', (status, expected) => {
    expect(states(status)).toEqual(expect.arrayContaining(expected));
  });

  it('отказ обрывается на решении: шагов подписи и денег нет', () => {
    const keys = states('REJECTED').map((item) => item.split(':')[0]);
    expect(keys.at(-1)).toBe('decision');
    expect(keys).not.toContain('signing');
  });

  it('отозвана и истекла: пояснение вместо шагов', () => {
    const withdrawn = buildTimeline({ ...base, status: 'WITHDRAWN' });
    expect(withdrawn.steps).toEqual([]);
    expect(withdrawn.note).toBe('Заявка отозвана вами');
    expect(buildTimeline({ ...base, status: 'EXPIRED' }).note).toContain('Срок истёк');
  });

  it('черновик и незнакомый статус — без шагов', () => {
    expect(buildTimeline({ ...base, status: 'DRAFT' }).steps).toEqual([]);
    expect(buildTimeline({ ...base, status: 'WHAT' }).steps).toEqual([]);
  });

  it('первый шаг показывает дату приёма, деньги — сумму, подписанный договор без даты', () => {
    const done = buildTimeline({ ...base, status: 'DISBURSED' });
    expect(done.steps[0]?.text).toMatch(/21\sоктября, 12:04/);
    expect(done.steps.at(-1)?.text).toContain('500');
    expect(done.steps.find((s) => s.key === 'signing')?.text).toBe('Договор подписан');
  });

  it('текущий шаг: идущий, а при решении — последний готовый', () => {
    expect(buildTimeline({ ...base, status: 'CHECKING' }).current?.key).toBe('checking');
    expect(buildTimeline({ ...base, status: 'APPROVED' }).current?.key).toBe('decision');
  });

  it('clientStepOf: у конечных без решения шага нет', () => {
    expect(clientStepOf('WITHDRAWN')).toBeNull();
    expect(clientStepOf('EXPIRED')).toBeNull();
    expect(clientStepOf('SIGNED')).toBe('signing');
  });
});
