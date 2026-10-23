import { screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { http } from 'msw';
import { describe, expect, it, vi } from 'vitest';
import { makeApplication, makeBankMe, makeMe, problemResponse } from '@/test/factories';
import { blockingA11yViolations } from '@/test/a11y';
import { renderApp, createTestQueryClient } from '@/test/render';
import { mockSessions } from '@/test/sessions';
import { server } from '@/test/server';
import { makeDecision } from '@/test/decisionFactory';
import { demo as t } from '@/texts/demo';

const persona = {
  code: 'sokolova',
  title: 'Соколова, исходный сценарий',
  inn: '001234567887',
  companyId: 'co-1',
  status: 'APPLIED',
  technical: false,
  expectedOutcome: 'APPROVED',
  application: { productCode: 'EXPRESS', amountRub: '800000', termMonths: 18 },
};
function scenarios() {
  server.use(
    http.get('*/api/demo/personas', () =>
      Response.json([
        persona,
        { ...persona, code: 't-test', title: 'Техническая персона', technical: true },
      ]),
    ),
  );
}

describe('демо-панель', () => {
  it('данные из API, технические скрыты, доступность, ссылки безопасны', async () => {
    mockSessions({
      config: { demoMode: true, docsLinks: { api: '/docs', bad: 'javascript:alert(1)' } },
    });
    scenarios();
    const { container } = renderApp('/demo');
    await screen.findByText(persona.title);
    expect(screen.getByText(persona.inn, { exact: false })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: t.technical })).toHaveAttribute(
      'aria-expanded',
      'false',
    );
    await userEvent.click(screen.getByRole('button', { name: t.technical }));
    await waitFor(() => expect(screen.getByText('Техническая персона')).toBeVisible());
    expect(screen.getByRole('link', { name: 'api' })).toHaveAttribute('href', '/docs');
    expect(screen.queryByRole('link', { name: 'bad' })).not.toBeInTheDocument();
    expect(await blockingA11yViolations(container)).toEqual([]);
  });
  it('сброс персоны только после подтверждения, с кодом, ждёт реального ответа', async () => {
    mockSessions({ config: { demoMode: true, demoCodeRequired: true } });
    scenarios();
    let finish: (() => void) | undefined;
    const gate = new Promise<void>((resolve) => {
      finish = resolve;
    });
    const calls: string[] = [];
    server.use(
      http.post('*/api/demo/personas/sokolova/reset', async ({ request }) => {
        calls.push(request.headers.get('X-Demo-Code') ?? '');
        await gate;
        return Response.json({
          status: 'DONE',
          companyId: 'co-1',
          generation: 2,
          steps: [{ step: 'MOCKS', title: 'моки', status: 'DONE' }],
          durationMs: 30,
          finishedAt: '2026-10-23T00:00:00Z',
        });
      }),
    );
    renderApp('/demo');
    await screen.findByText(persona.title);
    await userEvent.type(screen.getByLabelText(t.code), 'stand-code');
    await userEvent.click(screen.getAllByRole('button', { name: t.resetOne })[0]!);
    const modal = await screen.findByRole('dialog');
    expect(calls).toEqual([]);
    await userEvent.click(within(modal).getByRole('button', { name: t.confirm }));
    expect(await within(modal).findByText(t.resetting)).toBeInTheDocument();
    expect(screen.queryByText(t.resetDone, { exact: false })).not.toBeInTheDocument();
    finish?.();
    expect(await screen.findByText(t.resetDone, { exact: false })).toBeInTheDocument();
    expect(calls).toEqual(['stand-code']);
  });
  it('облачная ошибка кода не выдаёт успешный сброс', async () => {
    mockSessions({ config: { demoMode: true, demoCodeRequired: true } });
    scenarios();
    server.use(
      http.post('*/api/demo/reset', () =>
        problemResponse({ status: 403, code: 'DEMO_CODE_REQUIRED' }),
      ),
    );
    renderApp('/demo');
    await screen.findByText(persona.title);
    await userEvent.click(screen.getByRole('button', { name: t.resetAll }));
    const modal = await screen.findByRole('dialog');
    expect(within(modal).getByRole('button', { name: t.confirm })).toBeDisabled();
    await userEvent.click(within(modal).getByRole('button', { name: t.cancel }));
    await userEvent.type(screen.getByLabelText(t.code), 'wrong');
    await userEvent.click(screen.getByRole('button', { name: t.resetAll }));
    await userEvent.click(
      within(await screen.findByRole('dialog')).getByRole('button', { name: t.confirm }),
    );
    expect(await screen.findByText(/Нужен верный код стенда/)).toBeInTheDocument();
    expect(screen.queryByText(t.resetDone, { exact: false })).not.toBeInTheDocument();
  });
  it('полоса сбоя в банковской зоне и выдвижная панель', async () => {
    mockSessions({ bank: makeBankMe(), config: { demoMode: true } });
    scenarios();
    server.use(
      http.get('*/api/demo/chaos', () =>
        Response.json([{ system: 'credit_bureau', available: true, mode: 'DOWN' }]),
      ),
    );
    renderApp('/bank');
    expect(await screen.findByText(t.active)).toBeInTheDocument();
    await userEvent.click(screen.getByRole('button', { name: t.open }));
    expect(await screen.findByRole('link', { name: t.full })).toHaveAttribute('href', '/demo');
    expect(await screen.findByText(persona.title)).toBeInTheDocument();
  });
  it('переключение сбоя подтверждается API и обновляет общую полосу', async () => {
    mockSessions({ config: { demoMode: true } });
    scenarios();
    let mode = 'OK';
    const calls: unknown[] = [];
    server.use(
      http.get('*/api/demo/chaos', () => Response.json([{ system: 'tax', available: true, mode }])),
      http.put('*/api/demo/chaos/tax', async ({ request }) => {
        const body = (await request.json()) as { mode: string };
        calls.push(body);
        mode = body.mode;
        return Response.json({ system: 'tax', available: true, mode });
      }),
    );
    renderApp('/demo');
    const select = await screen.findByRole('combobox', {
      name: `${t.chooseMode}: ${t.systems.tax}`,
    });
    await userEvent.click(select);
    await userEvent.click(
      (await screen.findAllByRole('option', { name: t.modes.DOWN, hidden: true })).at(-1)!,
    );
    await userEvent.click(screen.getByRole('button', { name: t.set }));
    expect(await screen.findByText(t.queued)).toBeInTheDocument();
    expect(await screen.findByText(t.active)).toBeInTheDocument();
    expect(calls).toEqual([{ mode: 'DOWN', latencyMs: null }]);
  });
  it('демо выключено: управляющих элементов нет', async () => {
    mockSessions({ config: { demoMode: false } });
    renderApp('/login');
    await screen.findByTestId('demo-banner');
    expect(screen.queryByRole('button', { name: t.open })).not.toBeInTheDocument();
  });
  it('банк открывается отдельно; клиентская сессия остаётся в кэше', async () => {
    mockSessions({ client: makeMe(), config: { demoMode: true } });
    scenarios();
    const tab = { opener: {}, location: { href: 'about:blank' }, close: vi.fn() };
    const open = vi.spyOn(window, 'open').mockReturnValue(tab as unknown as Window);
    server.use(http.post('*/api/auth/bank-demo-login', () => Response.json(makeBankMe())));
    const queryClient = createTestQueryClient();
    const clientSession = makeMe();
    queryClient.setQueryData(['session', 'client'], clientSession);
    renderApp('/demo', queryClient);
    await userEvent.click(await screen.findByRole('button', { name: t.bank }));
    await waitFor(() => expect(tab.location.href).toBe('/bank'));
    expect(open).toHaveBeenCalledWith('about:blank', '_blank');
    expect(tab.opener).toBeNull();
    expect(queryClient.getQueryData(['session', 'bank'])).toBeDefined();
    expect(queryClient.getQueryData(['session', 'client'])).toEqual(clientSession);
    open.mockRestore();
  });
  it('подсказка ожидаемого исхода закрыта по умолчанию', async () => {
    mockSessions({ client: makeMe(), config: { demoMode: true } });
    scenarios();
    server.use(
      http.get('*/api/applications/app-1', () =>
        Response.json(
          makeApplication({
            companyId: 'co-1',
            productCode: 'EXPRESS',
            amountRub: 800000,
            termMonths: 18,
            status: 'MANUAL_REVIEW',
            allowedActions: [],
          }),
        ),
      ),
    );
    server.use(http.get('*/api/applications/app-1/decision', () => Response.json(makeDecision())));
    renderApp('/applications/app-1');
    const hint = await screen.findByTestId('demo-expected-hint');
    const button = within(hint).getByRole('button', { name: t.hint });
    expect(button).toHaveAttribute('aria-expanded', 'false');
    await userEvent.click(button);
    await waitFor(() => expect(within(hint).getByText(t.hintHelp)).toBeVisible());
  });
});
