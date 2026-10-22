import { describe, expect, it } from 'vitest';
import { innProblem, normalizeInn } from './inn';

describe('innProblem', () => {
  it('принимает ИНН с верной контрольной суммой: 12 цифр и 10 цифр', () => {
    expect(innProblem('001234567887')).toBeNull();
    expect(innProblem('0012345673')).toBeNull();
    expect(innProblem('7707083893')).toBeNull();
  });

  it('длина не 10 и не 12 — проблема длины', () => {
    expect(innProblem('')).toBe('length');
    expect(innProblem('123')).toBe('length');
    expect(innProblem('00123456788')).toBe('length');
    expect(innProblem('0012345678871')).toBe('length');
  });

  it('опечатка в контрольной цифре — проблема суммы', () => {
    expect(innProblem('001234567888')).toBe('checksum');
    expect(innProblem('0012345674')).toBe('checksum');
    expect(innProblem('001234568887')).toBe('checksum');
  });
});

describe('normalizeInn', () => {
  it('оставляет цифры и режет до 12', () => {
    expect(normalizeInn('00 12-34 abc')).toBe('001234');
    expect(normalizeInn('1234567890123456')).toBe('123456789012');
  });
});
