import { readFileSync, readdirSync, statSync } from 'node:fs';
import { join, relative } from 'node:path';
import { render } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import { request } from '@/api/client';
import { blockingA11yViolations } from './a11y';
import { MockEventSource } from './eventSource';

/** Мета-тесты обвязки (T-406): сама обвязка должна ловить то, ради чего она нужна */

describe('проверка доступности в экранных тестах', () => {
  it('экран с нарушением (картинка без подписи) роняет проверку', async () => {
    const { container } = render(
      <main>
        {/* eslint-disable-next-line jsx-a11y/alt-text -- нарушение сделано нарочно: проверяем, что axe его ловит */}
        <img src="x.png" />
      </main>,
    );
    const violations = await blockingA11yViolations(container);
    expect(violations.some((text) => text.startsWith('image-alt'))).toBe(true);
  });

  it('экран без нарушений проходит', async () => {
    const { container } = render(
      <main>
        <h1>Заголовок</h1>
        <button type="button">Отправить заявку</button>
      </main>,
    );
    expect(await blockingA11yViolations(container)).toEqual([]);
  });

  it('кнопка без названия — серьёзное нарушение', async () => {
    const { container } = render(
      <main>
        <h1>Заголовок</h1>
        {/* eslint-disable-next-line jsx-a11y/control-has-associated-label -- нарушение сделано нарочно */}
        <button type="button" />
      </main>,
    );
    expect((await blockingA11yViolations(container)).some((t) => t.startsWith('button-name'))).toBe(
      true,
    );
  });
});

describe('MSW', () => {
  it('запрос без обработчика — сбой, а не тихий ответ: данные в тестах всегда по схеме', async () => {
    await expect(request('/api/v1/no-such-handler')).rejects.toMatchObject({
      code: 'NETWORK_ERROR',
    });
  });
});

describe('мок EventSource', () => {
  it('управляется из теста', () => {
    const seen: string[] = [];
    const source = new MockEventSource('/stream');
    source.addEventListener('open', () => seen.push('open'));
    source.addEventListener('status_changed', (event) =>
      seen.push(`${event.type}:${(event as MessageEvent).lastEventId}`),
    );
    source.addEventListener('error', () => seen.push('error'));

    source.open();
    source.emit('status_changed', { a: 1 }, 7);
    source.fail({ closed: true });

    expect(seen).toEqual(['open', 'status_changed:7', 'error']);
    expect(source.readyState).toBe(MockEventSource.CLOSED);
    expect(MockEventSource.latest()).toBe(source);
  });

  it('removeEventListener и close', () => {
    const source = new MockEventSource('/stream');
    const seen: string[] = [];
    const listener = () => seen.push('x');
    source.addEventListener('open', listener);
    source.removeEventListener('open', listener);
    source.open();
    expect(seen).toEqual([]);
    source.close();
    expect(source.readyState).toBe(MockEventSource.CLOSED);
  });

  it('latest без потока — понятная ошибка', () => {
    MockEventSource.reset();
    expect(() => MockEventSource.latest()).toThrow(/EventSource/);
  });
});

describe('нет обращений к внешним адресам (T-400)', () => {
  const srcRoot = join(import.meta.dirname, '..');
  const webRoot = join(srcRoot, '..');

  function listSources(dir: string): string[] {
    return readdirSync(dir).flatMap((name) => {
      const full = join(dir, name);
      if (statSync(full).isDirectory())
        return name === 'generated' || name === 'test' ? [] : listSources(full);
      return /\.(ts|tsx|css|html|svg)$/.test(name) && !/\.test\.(ts|tsx)$/.test(name) ? [full] : [];
    });
  }

  it('в исходниках нет ссылок на CDN, шрифты и скрипты чужих сайтов', () => {
    const files = [
      ...listSources(srcRoot),
      join(webRoot, 'index.html'),
      join(webRoot, 'public/favicon.svg'),
    ];
    const offenders: string[] = [];
    for (const file of files) {
      const text = readFileSync(file, 'utf8');
      for (const match of text.matchAll(/https?:\/\/[^\s"'`)<>]+/g)) {
        const url = match[0];
        // xmlns в SVG — не запрос; адрес разработки api вынесен в конфиг сборки, не в src
        if (url.startsWith('http://www.w3.org/')) continue;
        offenders.push(`${relative(webRoot, file)}: ${url}`);
      }
    }
    expect(offenders).toEqual([]);
  });
});
