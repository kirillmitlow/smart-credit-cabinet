import { act, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { http } from 'msw';
import { describe, expect, it } from 'vitest';
import type { ApplicationTimelineOut } from '@/api/generated/model';
import { getGetApplicationTimelineQueryKey } from '@/api/generated/api';
import { makeApplication, makeMe, problemResponse } from '@/test/factories';
import { makeDecision } from '@/test/decisionFactory';
import { MockEventSource } from '@/test/eventSource';
import { renderApp } from '@/test/render';
import { mockSessions } from '@/test/sessions';
import { server } from '@/test/server';
import { timelineNotes, timelineProgress } from '@/texts';
import { timelineFromEvents } from './timelineModel';

function progress(overrides: Partial<ApplicationTimelineOut> = {}): ApplicationTimelineOut {
  return {
    applicationId: 'app-1',
    version: 1,
    lastEventId: 20,
    noteKey: null,
    steps: [
      {
        key: 'submitted',
        state: 'done',
        textKey: 'submitted.done',
        params: { date: '2026-10-21T09:04:00Z' },
      },
      { key: 'checking', state: 'running', textKey: 'checking.running' },
      { key: 'evaluating', state: 'waiting', textKey: 'evaluating.waiting' },
      { key: 'decision', state: 'waiting', textKey: 'decision.waiting' },
      { key: 'signing', state: 'waiting', textKey: 'signing.waiting' },
      { key: 'money', state: 'waiting', textKey: 'money.waiting' },
    ],
    checks: [
      { key: 'registry', state: 'done', textKey: 'checks.registry' },
      { key: 'taxes', state: 'delayed', textKey: 'checks.taxes' },
      { key: 'creditHistory', state: 'running', textKey: 'checks.creditHistory' },
      { key: 'turnover', state: 'done', textKey: 'checks.turnover' },
    ],
    ...overrides,
  };
}

describe('лента событий заявки', () => {
  it('переводит только известные ключи, сохраняет дату подписи и пояснение задержки', () => {
    const model = timelineFromEvents(
      progress({
        noteKey: 'sourceDelayed',
        steps: [
          {
            key: 'signing',
            state: 'done',
            textKey: 'signing.done',
            params: { date: '2026-10-21T09:04:00Z' },
          },
          { key: 'money', state: 'done', textKey: 'money.done' },
          { key: 'decision', state: 'done', textKey: 'SECRET_SCORING_REASON' },
        ],
      }),
    );
    expect(model.steps[0]?.text).toMatch(/Договор подписан 21\sоктября, 12:04/);
    expect(model.steps[1]?.text).toBe(timelineProgress.moneyDone);
    expect(model.steps[2]?.text).toBeNull();
    expect(model.note).toBe(timelineNotes.sourceDelayed);
  });

  it('обновляет проверки из SSE без смены статуса и не дублирует шаги', async () => {
    mockSessions({ client: makeMe() });
    let data = progress();
    let calls = 0;
    server.use(
      http.get('*/api/applications/app-1', () =>
        Response.json(makeApplication({ status: 'CHECKING' })),
      ),
      http.get('*/api/applications/app-1/timeline', () => {
        calls += 1;
        return Response.json(data);
      }),
    );
    renderApp('/applications/app-1');
    const list = await screen.findByTestId('timeline');
    await waitFor(() =>
      expect(list.querySelector('[data-check="taxes"]')).toHaveAttribute('data-state', 'delayed'),
    );
    expect(list.querySelector('[data-check="registry"]')).toHaveTextContent('✓');
    expect(list.querySelector('[data-check="taxes"]')).not.toHaveTextContent('✓');
    expect(list).toHaveTextContent(timelineProgress.checkState.delayed);
    await waitFor(() => expect(MockEventSource.instances.length).toBeGreaterThan(0));
    const previous = calls;
    data = {
      ...data,
      lastEventId: 21,
      checks: data.checks.map((check) => ({ ...check, state: 'done' })),
    };
    act(() => MockEventSource.latest().emit('step_done', {}, 21));
    await waitFor(() => expect(calls).toBeGreaterThan(previous));
    await waitFor(() =>
      expect(list.querySelector('[data-check="taxes"]')).toHaveAttribute('data-state', 'done'),
    );
    expect(list.children).toHaveLength(6);
  });

  it('не показывает галочки прежней версии и позволяет повторить неудачную загрузку', async () => {
    mockSessions({ client: makeMe() });
    let fail = true;
    server.use(
      http.get('*/api/applications/app-1', () =>
        Response.json(makeApplication({ status: 'CHECKING', version: 2 })),
      ),
      http.get('*/api/applications/app-1/timeline', () =>
        fail
          ? problemResponse({ status: 503, code: 'SERVICE_UNAVAILABLE' })
          : Response.json(progress({ version: 2 })),
      ),
    );
    renderApp('/applications/app-1');
    const warning = await screen.findByTestId('timeline-unavailable');
    expect(screen.getByTestId('timeline').querySelector('[data-check]')).toBeNull();
    fail = false;
    await userEvent.click(within(warning).getByRole('button', { name: 'Повторить' }));
    await waitFor(() =>
      expect(screen.queryByTestId('timeline-unavailable')).not.toBeInTheDocument(),
    );
    await waitFor(() =>
      expect(
        screen.getByTestId('timeline').querySelector('[data-check="registry"]'),
      ).toHaveAttribute('data-state', 'done'),
    );
  });

  it('не принимает журнал другой версии заявки даже при успешном ответе', async () => {
    mockSessions({ client: makeMe() });
    server.use(
      http.get('*/api/applications/app-1', () =>
        Response.json(makeApplication({ status: 'MANUAL_REVIEW', version: 3 })),
      ),
      http.get('*/api/applications/app-1/timeline', () => Response.json(progress({ version: 2 }))),
      http.get('*/api/applications/app-1/decision', () =>
        Response.json(makeDecision({ outcome: 'MANUAL_REVIEW' })),
      ),
    );
    const { queryClient } = renderApp('/applications/app-1');
    const list = await screen.findByTestId('timeline');
    await waitFor(() =>
      expect(
        queryClient.getQueryData([...getGetApplicationTimelineQueryKey('app-1'), 3]),
      ).toMatchObject({ data: { version: 2 } }),
    );
    expect(list.querySelector('[data-check]')).toBeNull();
  });
});
