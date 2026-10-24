import { readFileSync, readdirSync } from 'node:fs';
import { join } from 'node:path';
import { describe, expect, it } from 'vitest';
import { AppError } from '@/api/errors';
import { errorTexts, errorView } from '.';

/** The API has no closed error enum. Check literal AppError/conflict codes in the actual source,
 * alongside the existing 50-07 contract list. Dynamic/integration codes keep the generic fallback. */
function pythonSources(dir: string): string[] {
  return readdirSync(dir, { withFileTypes: true }).flatMap((entry) => {
    const path = join(dir, entry.name);
    if (entry.isDirectory()) return entry.name === '__pycache__' ? [] : pythonSources(path);
    return entry.name.endsWith('.py') ? [readFileSync(path, 'utf8')] : [];
  });
}

function literalErrorCodes(source: string): string[] {
  return [
    ...source.matchAll(/\b(?:AppError\(\s*\d{3}\s*,|conflict\()\s*['"]([A-Z][A-Z0-9_]+)['"]/g),
  ].map((match) => match[1]!);
}

const codes = [
  ...new Set(
    pythonSources(join(import.meta.dirname, '../../../api/app')).flatMap(literalErrorCodes),
  ),
].sort();

describe('понятные ошибки для фактических API', () => {
  it('проверяет API, включая многострочные вызовы и conflict', () => {
    expect(codes.length).toBeGreaterThanOrEqual(80);
    expect(literalErrorCodes('raise AppError(\n 409,\n "NEW_ERROR", "private")')).toEqual([
      'NEW_ERROR',
    ]);
    expect(literalErrorCodes('raise conflict("VERSION_CONFLICT")')).toEqual(['VERSION_CONFLICT']);
  });

  it('у каждого явного кода сервера есть текст, а не общий ответ', () => {
    expect(codes.filter((code) => !Object.hasOwn(errorTexts, code))).toEqual([]);
  });

  it.each(codes)('%s не раскрывает detail и даёт собственное объяснение', (code) => {
    const view = errorView(
      new AppError({
        code,
        status: 409,
        detail: 'SECRET_INTERNAL_DETAIL',
        requestId: 'request-proof',
      }),
    );
    expect(view.text).toBe(errorTexts[code as keyof typeof errorTexts].text);
    expect(view.text).not.toContain('SECRET_INTERNAL_DETAIL');
    expect(view.requestId).toBe('request-proof');
  });
});
