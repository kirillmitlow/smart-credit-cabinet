import { afterEach, expect, it } from 'vitest';
import { currentZone } from './zone';

afterEach(() => window.history.replaceState({}, '', '/'));

it('банковский вход использует контекст банка до перехода в /bank', () => {
  window.history.replaceState({}, '', '/login?zone=bank');
  expect(currentZone()).toBe('bank');
});

it('обычный вход сохраняет клиентский контекст', () => {
  window.history.replaceState({}, '', '/login?next=/bank');
  expect(currentZone()).toBe('client');
});
