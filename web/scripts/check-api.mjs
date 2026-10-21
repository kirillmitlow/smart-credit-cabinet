// Клиент в src/api/generated/ должен совпадать со схемой docs/api/api.openapi.json (T-402).
// Перегенерируем клиент поверх текущего и сравниваем файлы до и после. Git не нужен: работает в CI и локально.
import { spawnSync } from 'node:child_process';
import { createHash } from 'node:crypto';
import { existsSync, readdirSync, readFileSync, statSync } from 'node:fs';
import { join } from 'node:path';

const generatedDir = 'src/api/generated';

function snapshot(dir) {
  const result = new Map();
  if (!existsSync(dir)) return result;
  const walk = (current) => {
    for (const name of readdirSync(current)) {
      const full = join(current, name);
      if (statSync(full).isDirectory()) walk(full);
      else result.set(full, createHash('sha256').update(readFileSync(full)).digest('hex'));
    }
  };
  walk(dir);
  return result;
}

const before = snapshot(generatedDir);
const run = spawnSync('pnpm', ['exec', 'orval', '--config', 'orval.config.ts'], {
  stdio: ['ignore', 'ignore', 'inherit'],
});
if (run.status !== 0) process.exit(run.status ?? 1);
const after = snapshot(generatedDir);

const differences = [];
for (const [file, hash] of after) {
  if (!before.has(file)) differences.push(`добавлен: ${file}`);
  else if (before.get(file) !== hash) differences.push(`изменён: ${file}`);
}
for (const file of before.keys()) {
  if (!after.has(file)) differences.push(`удалён: ${file}`);
}

if (differences.length > 0) {
  console.error('Клиент в src/api/generated/ не совпадает со схемой docs/api/api.openapi.json:');
  for (const line of differences) console.error(`  ${line}`);
  console.error('Выполните `pnpm gen:api` в web/ и закоммитьте результат.');
  process.exit(1);
}
console.log('Клиент совпадает со схемой.');
