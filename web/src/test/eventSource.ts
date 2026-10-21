/**
 * Управляемый `EventSource` для тестов таймлайна и хука потока (T-406, Q-050 А).
 * Тест сам решает, когда поток «открылся», пришло событие или связь оборвалась.
 */
type Listener = (event: Event) => void;

export class MockEventSource {
  static readonly CONNECTING = 0;
  static readonly OPEN = 1;
  static readonly CLOSED = 2;

  static instances: MockEventSource[] = [];

  /** Последний открытый поток или ошибка, если потока ещё нет */
  static latest(): MockEventSource {
    const last = MockEventSource.instances.at(-1);
    if (!last) throw new Error('EventSource ещё не создан');
    return last;
  }

  readonly url: string;
  readonly withCredentials = false;
  readyState: number = MockEventSource.CONNECTING;
  private readonly listeners = new Map<string, Set<Listener>>();

  constructor(url: string | URL) {
    this.url = String(url);
    MockEventSource.instances.push(this);
  }

  addEventListener(type: string, listener: Listener): void {
    const set = this.listeners.get(type) ?? new Set<Listener>();
    set.add(listener);
    this.listeners.set(type, set);
  }

  removeEventListener(type: string, listener: Listener): void {
    this.listeners.get(type)?.delete(listener);
  }

  close(): void {
    this.readyState = MockEventSource.CLOSED;
  }

  private dispatch(type: string, event: Event): void {
    for (const listener of this.listeners.get(type) ?? []) listener(event);
  }

  // Управление из теста

  /** Сервер ответил, поток открыт */
  open(): void {
    this.readyState = MockEventSource.OPEN;
    this.dispatch('open', new Event('open'));
  }

  /** Пришло событие. `id` — номер события аудита (`Last-Event-ID`) */
  emit(type: string, data: unknown = {}, id?: string | number): void {
    const event = new MessageEvent(type, {
      data: JSON.stringify(data),
      lastEventId: id === undefined ? '' : String(id),
    });
    this.dispatch(type, event);
  }

  /** Обрыв. `closed: true` — браузер не будет переподключаться сам (например, ответ не 200) */
  fail(options: { closed?: boolean } = {}): void {
    this.readyState = options.closed ? MockEventSource.CLOSED : MockEventSource.CONNECTING;
    this.dispatch('error', new Event('error'));
  }

  static reset(): void {
    MockEventSource.instances = [];
  }
}

export function installMockEventSource(): void {
  MockEventSource.reset();
  Object.defineProperty(globalThis, 'EventSource', {
    value: MockEventSource,
    configurable: true,
    writable: true,
  });
}
