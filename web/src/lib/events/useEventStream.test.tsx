import type { ReactNode } from 'react';
import { QueryClientProvider, useQuery, type QueryClient } from '@tanstack/react-query';
import { act, render, renderHook, screen, waitFor } from '@testing-library/react';
import { http, HttpResponse } from 'msw';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { apiGet } from '@/api/client';
import { MockEventSource } from '@/test/eventSource';
import { createTestQueryClient } from '@/test/render';
import { server } from '@/test/server';
import {
  MAX_FAILURES_BEFORE_POLLING,
  POLL_INTERVAL_MS,
  RECONNECT_DELAY_MS,
  streamUrl,
  useEventStream,
  type UseEventStreamOptions,
} from './useEventStream';

function setup(options: Partial<UseEventStreamOptions> = {}) {
  const queryClient = createTestQueryClient();
  const wrapper = ({ children }: { children: ReactNode }) => (
    <QueryClientProvider client={queryClient}>{children}</QueryClientProvider>
  );
  const onAuthExpired = vi.fn();
  const view = renderHook(
    (props: Partial<UseEventStreamOptions>) =>
      useEventStream({ zone: 'client', enabled: true, onAuthExpired, ...options, ...props }),
    { wrapper },
  );
  return { queryClient, onAuthExpired, ...view };
}

function seed(queryClient: QueryClient) {
  const keys = {
    application: ['/api/v1/applications/app-1'] as const,
    list: ['/api/v1/applications'] as const,
    timeline: ['/api/v1/applications/app-1/timeline'] as const,
    tasks: ['/api/v1/tasks'] as const,
    notifications: ['/api/v1/notifications'] as const,
    home: ['/api/v1/home'] as const,
    loans: ['/api/v1/loans'] as const,
    contracts: ['/contracts/contract-1'] as const,
    offers: ['/offers/offer-1'] as const,
    documents: ['/documents'] as const,
  };
  for (const key of Object.values(keys)) queryClient.setQueryData(key, { seeded: true });
  return keys;
}

const invalidated = (queryClient: QueryClient, key: readonly unknown[]) =>
  queryClient.getQueryState(key)?.isInvalidated === true;

afterEach(() => {
  vi.useRealTimers();
});

describe('подключение', () => {
  it('открывает один поток с зоной и показывает состояния', () => {
    const { result } = setup({ zone: 'bank' });
    expect(MockEventSource.instances).toHaveLength(1);
    expect(MockEventSource.latest().url).toBe('/api/v1/events/stream?zone=bank');
    expect(result.current).toBe('connecting');

    act(() => MockEventSource.latest().open());
    expect(result.current).toBe('connected');
  });

  it('без сессии (enabled=false) поток не открывается', () => {
    const { result } = setup({ enabled: false });
    expect(MockEventSource.instances).toHaveLength(0);
    expect(result.current).toBe('connecting');
  });

  it('при выходе закрывает поток', () => {
    const { unmount } = setup();
    const source = MockEventSource.latest();
    unmount();
    expect(source.readyState).toBe(MockEventSource.CLOSED);
  });

  it('streamUrl добавляет lastEventId только когда он есть', () => {
    expect(streamUrl('client', null)).toBe('/api/v1/events/stream?zone=client');
    expect(streamUrl('client', '41')).toBe('/api/v1/events/stream?zone=client&lastEventId=41');
  });
});

describe('карта событий → сброс кэша', () => {
  it('status_changed и step_done сбрасывают заявки, таймлайн, список и главную', async () => {
    const { queryClient } = setup();
    const keys = seed(queryClient);
    act(() => MockEventSource.latest().open());

    act(() => MockEventSource.latest().emit('status_changed', { applicationId: 'app-1' }, 1));
    await waitFor(() => expect(invalidated(queryClient, keys.application)).toBe(true));
    expect(invalidated(queryClient, keys.timeline)).toBe(true);
    expect(invalidated(queryClient, keys.list)).toBe(true);
    expect(invalidated(queryClient, keys.home)).toBe(true);
    expect(invalidated(queryClient, keys.tasks)).toBe(false);
    expect(invalidated(queryClient, keys.loans)).toBe(true);
    expect(invalidated(queryClient, keys.contracts)).toBe(true);
    expect(invalidated(queryClient, keys.offers)).toBe(true);
  });

  it('step_done делает то же', async () => {
    const { queryClient } = setup();
    const keys = seed(queryClient);
    act(() => MockEventSource.latest().emit('step_done', { applicationId: 'app-1' }, 2));
    await waitFor(() => expect(invalidated(queryClient, keys.timeline)).toBe(true));
    expect(invalidated(queryClient, keys.tasks)).toBe(true);
    expect(invalidated(queryClient, keys.documents)).toBe(true);
  });

  it('task_created сбрасывает задачи, уведомления и главную', async () => {
    const { queryClient } = setup();
    const keys = seed(queryClient);
    act(() => MockEventSource.latest().emit('task_created', {}, 3));
    await waitFor(() => expect(invalidated(queryClient, keys.tasks)).toBe(true));
    expect(invalidated(queryClient, keys.notifications)).toBe(true);
    expect(invalidated(queryClient, keys.home)).toBe(true);
    expect(invalidated(queryClient, keys.application)).toBe(false);
  });

  it('resync сбрасывает всё', async () => {
    const { queryClient } = setup();
    const keys = seed(queryClient);
    act(() => MockEventSource.latest().emit('resync', {}, 4));
    await waitFor(() => expect(invalidated(queryClient, keys.loans)).toBe(true));
    expect(invalidated(queryClient, keys.application)).toBe(true);
  });

  it('повтор события с тем же номером не сбрасывает кэш второй раз', () => {
    const { queryClient } = setup();
    const spy = vi.spyOn(queryClient, 'invalidateQueries');
    act(() => MockEventSource.latest().emit('status_changed', {}, 10));
    act(() => MockEventSource.latest().emit('status_changed', {}, 10));
    act(() => MockEventSource.latest().emit('status_changed', {}, 9));
    expect(spy).toHaveBeenCalledTimes(1);
    act(() => MockEventSource.latest().emit('status_changed', {}, 11));
    expect(spy).toHaveBeenCalledTimes(2);
  });

  it('auth_expired вызывает обработчик и не трогает кэш', () => {
    const { queryClient, onAuthExpired } = setup();
    const spy = vi.spyOn(queryClient, 'invalidateQueries');
    act(() => MockEventSource.latest().emit('auth_expired', {}));
    expect(onAuthExpired).toHaveBeenCalledTimes(1);
    expect(spy).not.toHaveBeenCalled();
  });
});

describe('экран перечитывается после события без перезагрузки', () => {
  /** Мини-таймлайн: читает шаги обычным запросом, поток только сбрасывает кэш */
  function Timeline() {
    const { data } = useQuery({
      queryKey: ['/api/v1/applications/app-1/timeline'],
      queryFn: () => apiGet<{ steps: string[] }>('/api/v1/applications/app-1/timeline'),
    });
    return (
      <ol aria-label="timeline">
        {(data?.steps ?? []).map((step) => (
          <li key={step}>{step}</li>
        ))}
      </ol>
    );
  }
  function Probe() {
    useEventStream({ zone: 'client', enabled: true });
    return <Timeline />;
  }

  it('step_done сдвигает шаг, повтор события шаг не дублирует', async () => {
    let doneSteps = ['submitted'];
    let requests = 0;
    server.use(
      http.get('*/api/v1/applications/app-1/timeline', () => {
        requests += 1;
        return HttpResponse.json({ steps: doneSteps });
      }),
    );
    const queryClient = createTestQueryClient();
    render(
      <QueryClientProvider client={queryClient}>
        <Probe />
      </QueryClientProvider>,
    );
    await waitFor(() => expect(screen.getAllByRole('listitem')).toHaveLength(1));
    act(() => MockEventSource.latest().open());

    // сервер продвинул заявку и прислал событие
    doneSteps = ['submitted', 'checking'];
    act(() => MockEventSource.latest().emit('step_done', { applicationId: 'app-1' }, 21));
    await waitFor(() => expect(screen.getAllByRole('listitem')).toHaveLength(2));
    expect(screen.getByText('checking')).toBeInTheDocument();
    const afterFirst = requests;

    // то же событие пришло повторно (переподключение): шаг не дублируется, лишнего запроса нет
    act(() => MockEventSource.latest().emit('step_done', { applicationId: 'app-1' }, 21));
    await new Promise((resolve) => setTimeout(resolve, 30));
    expect(screen.getAllByRole('listitem')).toHaveLength(2);
    expect(requests).toBe(afterFirst);
  });

  it('после обрыва и resync состояние совпадает с сервером', async () => {
    let doneSteps = ['submitted'];
    server.use(
      http.get('*/api/v1/applications/app-1/timeline', () =>
        HttpResponse.json({ steps: doneSteps }),
      ),
    );
    const queryClient = createTestQueryClient();
    render(
      <QueryClientProvider client={queryClient}>
        <Probe />
      </QueryClientProvider>,
    );
    await waitFor(() => expect(screen.getAllByRole('listitem')).toHaveLength(1));
    act(() => MockEventSource.latest().open());

    // связь оборвалась, пока на сервере прошло несколько шагов
    act(() => MockEventSource.latest().fail());
    doneSteps = ['submitted', 'checking', 'evaluating'];
    act(() => MockEventSource.latest().emit('resync', {}, 30));
    await waitFor(() => expect(screen.getAllByRole('listitem')).toHaveLength(3));
  });
});

describe('обрыв, переподключение и запасной опрос', () => {
  it('после обрыва показывает «восстанавливаем связь» и возвращается к потоку', () => {
    const { result, queryClient } = setup();
    const spy = vi.spyOn(queryClient, 'invalidateQueries');
    act(() => MockEventSource.latest().open());
    act(() => MockEventSource.latest().fail());
    expect(result.current).toBe('reconnecting');

    act(() => MockEventSource.latest().open());
    expect(result.current).toBe('connected');
    // пока связи не было, события могли пройти мимо: кэш перечитывается
    expect(spy).toHaveBeenCalled();
  });

  it('закрытый браузером поток открывается заново через 3 с с номером последнего события', () => {
    vi.useFakeTimers();
    setup();
    act(() => MockEventSource.latest().open());
    act(() => MockEventSource.latest().emit('status_changed', {}, 55));
    act(() => MockEventSource.latest().fail({ closed: true }));
    expect(MockEventSource.instances).toHaveLength(1);

    act(() => {
      vi.advanceTimersByTime(RECONNECT_DELAY_MS);
    });
    expect(MockEventSource.instances).toHaveLength(2);
    expect(MockEventSource.latest().url).toBe('/api/v1/events/stream?zone=client&lastEventId=55');
  });

  it('обрыв на 10 с: восстанавливаем связь, затем опрос раз в 5 с, затем возврат на поток', () => {
    vi.useFakeTimers();
    const { result, queryClient } = setup();
    const spy = vi.spyOn(queryClient, 'invalidateQueries');
    act(() => MockEventSource.latest().open());
    expect(result.current).toBe('connected');

    // первая и вторая неудачи — «восстанавливаем связь»
    for (let attempt = 1; attempt < MAX_FAILURES_BEFORE_POLLING; attempt += 1) {
      act(() => MockEventSource.latest().fail({ closed: true }));
      expect(result.current).toBe('reconnecting');
      act(() => {
        vi.advanceTimersByTime(RECONNECT_DELAY_MS);
      });
    }

    // третья неудача — запасной опрос
    act(() => MockEventSource.latest().fail({ closed: true }));
    expect(result.current).toBe('polling');
    const callsAtStart = spy.mock.calls.length;
    act(() => {
      vi.advanceTimersByTime(POLL_INTERVAL_MS);
    });
    expect(spy.mock.calls.length).toBe(callsAtStart + 1);

    // поток ожил: возврат на «обновляется автоматически», опрос остановлен
    act(() => {
      vi.advanceTimersByTime(RECONNECT_DELAY_MS);
    });
    act(() => MockEventSource.latest().open());
    expect(result.current).toBe('connected');
    const callsAfterRecovery = spy.mock.calls.length;
    act(() => {
      vi.advanceTimersByTime(POLL_INTERVAL_MS * 3);
    });
    expect(spy.mock.calls.length).toBe(callsAfterRecovery);
  });

  it('при выходе из системы таймеры очищаются', () => {
    vi.useFakeTimers();
    const { unmount, queryClient } = setup();
    const spy = vi.spyOn(queryClient, 'invalidateQueries');
    for (let attempt = 0; attempt < MAX_FAILURES_BEFORE_POLLING; attempt += 1) {
      act(() => MockEventSource.latest().fail({ closed: true }));
      act(() => {
        vi.advanceTimersByTime(RECONNECT_DELAY_MS);
      });
    }
    unmount();
    const calls = spy.mock.calls.length;
    const instances = MockEventSource.instances.length;
    act(() => {
      vi.advanceTimersByTime(POLL_INTERVAL_MS * 4);
    });
    expect(spy.mock.calls.length).toBe(calls);
    expect(MockEventSource.instances.length).toBe(instances);
  });

  it('смена зоны переоткрывает поток', () => {
    const { rerender } = setup();
    const first = MockEventSource.latest();
    rerender({ zone: 'bank' });
    expect(first.readyState).toBe(MockEventSource.CLOSED);
    expect(MockEventSource.latest().url).toContain('zone=bank');
  });
});
