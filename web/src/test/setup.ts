import '@testing-library/jest-dom/vitest';
import { cleanup } from '@testing-library/react';
import { afterAll, afterEach, beforeAll, beforeEach, expect } from 'vitest';
import * as axeMatchers from 'vitest-axe/matchers';
import { installMockEventSource } from './eventSource';
import { server } from './server';

expect.extend(axeMatchers);

// jsdom: относительные адреса в fetch (Node) не разбираются без базы — подставляем origin страницы
const nativeFetch = globalThis.fetch.bind(globalThis);
globalThis.fetch = (input, init) =>
  typeof input === 'string' && input.startsWith('/')
    ? nativeFetch(new URL(input, window.location.origin), init)
    : nativeFetch(input, init);

// Mantine ждёт браузерные API, которых нет в jsdom
if (typeof window.matchMedia !== 'function') {
  Object.defineProperty(window, 'matchMedia', {
    writable: true,
    value: (query: string): MediaQueryList =>
      ({
        matches: false,
        media: query,
        onchange: null,
        addListener: () => undefined,
        removeListener: () => undefined,
        addEventListener: () => undefined,
        removeEventListener: () => undefined,
        dispatchEvent: () => false,
      }) as MediaQueryList,
  });
}
class ResizeObserverStub {
  observe(): void {}
  unobserve(): void {}
  disconnect(): void {}
}
globalThis.ResizeObserver ??= ResizeObserverStub;
if (!('scrollIntoView' in window.HTMLElement.prototype)) {
  Object.defineProperty(window.HTMLElement.prototype, 'scrollIntoView', {
    configurable: true,
    value: () => undefined,
  });
}

beforeAll(() => {
  // Запрос без обработчика — ошибка теста: данные всегда по схеме, а не случайные
  server.listen({ onUnhandledFrame: 'error' });
});

beforeEach(() => {
  installMockEventSource();
});

afterEach(() => {
  cleanup();
  server.resetHandlers();
  document.cookie.split(';').forEach((cookie) => {
    const name = cookie.split('=')[0]?.trim();
    if (name) document.cookie = `${name}=; expires=Thu, 01 Jan 1970 00:00:00 GMT; path=/`;
  });
  window.history.replaceState(null, '', '/');
});

afterAll(() => {
  server.close();
});
