import { describe, expect, it } from 'vitest';
import { indicativePayment, monthlyPayment } from './finance';

describe('monthlyPayment', () => {
  it('платёж 500 000 ₽ на 12 месяцев под 21,5% близок к оракулу 30-17 (46 677 ₽)', () => {
    expect(Math.abs(monthlyPayment(500_000, 12, 21.5) - 46_677)).toBeLessThan(150);
  });

  it('без процентов — просто делим на срок', () => {
    expect(monthlyPayment(120_000, 12, 0)).toBe(10_000);
  });

  it('нулевой вход — нулевой платёж', () => {
    expect(monthlyPayment(0, 12, 20)).toBe(0);
    expect(monthlyPayment(100_000, 0, 20)).toBe(0);
  });
});

describe('indicativePayment', () => {
  it('для продуктов с равными платежами считает', () => {
    expect(indicativePayment('EXPRESS', 500_000, 12)).toBeGreaterThan(40_000);
  });

  it('для остальных продуктов и пустых данных — null', () => {
    expect(indicativePayment('OVERDRAFT', 500_000, 12)).toBeNull();
    expect(indicativePayment('EXPRESS', null, 12)).toBeNull();
    expect(indicativePayment(null, 500_000, 12)).toBeNull();
    expect(indicativePayment('UNKNOWN', 500_000, 12)).toBeNull();
  });
});
