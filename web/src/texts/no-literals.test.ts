import { readFileSync, readdirSync, statSync } from 'node:fs';
import { join, relative } from 'node:path';
import { describe, expect, it } from 'vitest';

/**
 * Пользовательских строк вне `texts/` в экранах нет (T-405, 60-06): ищем кириллицу в коде компонентов
 * и экранов, не считая комментариев. Подписи для разработчика пишем по-английски.
 */
const srcRoot = join(import.meta.dirname, '..');
const scannedDirs = ['components', 'features', 'app'];

function listFiles(dir: string): string[] {
  return readdirSync(dir).flatMap((name) => {
    const full = join(dir, name);
    if (statSync(full).isDirectory()) return listFiles(full);
    return /\.(ts|tsx)$/.test(name) && !/\.test\.(ts|tsx)$/.test(name) ? [full] : [];
  });
}

function stripComments(source: string): string {
  return source.replace(/\/\*[\s\S]*?\*\//g, '').replace(/(^|[^:'"`])\/\/.*$/gm, '$1');
}

describe('тексты интерфейса лежат в texts/', () => {
  const files = scannedDirs.flatMap((dir) => listFiles(join(srcRoot, dir)));

  it('есть что проверять', () => {
    expect(files.length).toBeGreaterThan(10);
  });

  it('в компонентах и экранах нет кириллицы вне комментариев', () => {
    const offenders: string[] = [];
    for (const file of files) {
      const code = stripComments(readFileSync(file, 'utf8'));
      const lines = code.split('\n');
      lines.forEach((line, index) => {
        if (/[А-Яа-яЁё]/.test(line)) {
          offenders.push(`${relative(srcRoot, file)}:${index + 1}: ${line.trim()}`);
        }
      });
    }
    expect(offenders).toEqual([]);
  });
});
