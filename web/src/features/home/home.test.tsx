import { screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { http } from 'msw';
import { describe, expect, it } from 'vitest';
import { blockingA11yViolations } from '@/test/a11y';
import { makeApplication, makeCompanyChoice, makeMe, problemResponse } from '@/test/factories';
import { renderApp } from '@/test/render';
import { mockSessions } from '@/test/sessions';
import { server } from '@/test/server';
import { emptyStates, errorTexts, home, applicationForm } from '@/texts';

function mockList(items: ReturnType<typeof makeApplication>[]) {
  server.use(http.get('*/api/applications', () => Response.json({ items, nextCursor: null })));
}

describe('главная', () => {
  it('новая компания: честные пустые состояния и крупная кнопка', async () => {
    mockSessions({ client: makeMe() });
    const { container } = renderApp('/');
    expect(await screen.findByRole('heading', { level: 1, name: home.title })).toBeInTheDocument();
    expect(await screen.findByText(emptyStates.homeNoApplications.text)).toBeInTheDocument();
    expect(screen.getByText(emptyStates.tasks)).toBeInTheDocument();
    expect(screen.getByText(emptyStates.loans)).toBeInTheDocument();
    expect(screen.getByRole('link', { name: home.needMoney })).toHaveAttribute('href', '/wizard');
    const empty = within(screen.getByTestId('applications-empty'));
    expect(
      empty.getByRole('link', { name: emptyStates.homeNoApplications.action }),
    ).toHaveAttribute('href', '/wizard');
    expect(await blockingA11yViolations(container)).toEqual([]);
  });

  it('карточка заявки со статусом и «Открыть»; задача по решению', async () => {
    mockSessions({ client: makeMe() });
    mockList([
      makeApplication({
        id: 'a-1',
        status: 'APPROVED',
        allowedActions: ['ACCEPT_OFFER', 'WITHDRAW'],
      }),
    ]);
    const { container } = renderApp('/');
    const card = await screen.findByTestId('application-card');
    expect(within(card).getByTestId('application-status')).toHaveTextContent('Одобрено');
    expect(card).toHaveTextContent('Экспресс-кредит');
    expect(card).toHaveTextContent('500');
    expect(within(card).getByRole('link', { name: /Открыть/ })).toHaveAttribute(
      'href',
      '/applications/a-1',
    );
    expect(screen.getByText(/Посмотреть решение по заявке № АЗ-2026-000001/)).toBeInTheDocument();
    expect(await blockingA11yViolations(container)).toEqual([]);
  });

  it('черновик ведёт на продолжение формы', async () => {
    mockSessions({ client: makeMe() });
    mockList([makeApplication({ id: 'a-2' })]);
    renderApp('/');
    const card = await screen.findByTestId('application-card');
    expect(within(card).getByRole('link', { name: /Продолжить заявку/ })).toHaveAttribute(
      'href',
      '/applications/a-2/edit/1',
    );
  });

  it('блок заявок не загрузился: ошибка с повтором, остальное работает', async () => {
    mockSessions({ client: makeMe() });
    server.use(
      http.get('*/api/applications', () =>
        problemResponse({ status: 400, code: 'BAD_REQUEST', requestId: 'req-list' }),
      ),
    );
    renderApp('/');
    expect(await screen.findByText(errorTexts.BAD_REQUEST.text)).toBeInTheDocument();
    expect(screen.getByText(emptyStates.loans)).toBeInTheDocument();
    expect(screen.getByRole('link', { name: home.needMoney })).toBeInTheDocument();
  });

  it('компания не действует: подать заявку нельзя', async () => {
    mockSessions({
      client: makeMe({
        companies: [makeCompanyChoice({ status: 'LIQUIDATING', canApply: false })],
      }),
    });
    renderApp('/');
    expect(
      await screen.findByText(/Компания не действует \(в стадии ликвидации\)/),
    ).toBeInTheDocument();
    expect(screen.getByRole('button', { name: home.needMoney })).toBeDisabled();
    expect(screen.queryByRole('button', { name: home.startDirect })).not.toBeInTheDocument();
  });

  it('«Заполнить заявку сразу» создаёт черновик и открывает шаг «Условия»', async () => {
    const user = userEvent.setup();
    mockSessions({ client: makeMe() });
    const created = makeApplication({
      id: 'new-1',
      productCode: null,
      amountRub: null,
      termMonths: null,
    });
    let posts = 0;
    server.use(
      http.post('*/api/applications', () => {
        posts += 1;
        return Response.json(created, { status: 201 });
      }),
      http.get('*/api/applications/new-1', () => Response.json(created)),
    );
    renderApp('/');
    await user.click(await screen.findByRole('button', { name: home.startDirect }));
    expect(
      await screen.findByRole('heading', { level: 1, name: /Шаг 1 из 5: Условия/ }),
    ).toBeInTheDocument();
    expect(posts).toBe(1);
    expect(window.location.pathname).toBe('/applications/new-1/edit/1');
    expect(applicationForm.conditions.heading).toBeTruthy();
  });

  it('«Выйти» возвращает на вход', async () => {
    const user = userEvent.setup();
    mockSessions({ client: makeMe() });
    server.use(http.post('*/api/auth/logout', () => new Response(null, { status: 204 })));
    renderApp('/');
    await screen.findByRole('heading', { level: 1, name: home.title });
    mockSessions({ client: null });
    await user.click(screen.getByRole('button', { name: 'Выйти' }));
    expect(await screen.findByLabelText(/ИНН компании или ИП/)).toBeInTheDocument();
    expect(window.location.pathname).toBe('/login');
  });
});
