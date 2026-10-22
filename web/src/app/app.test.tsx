import { act, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { http } from 'msw';
import { describe, expect, it } from 'vitest';
import { apiGet } from '@/api/client';
import { blockingA11yViolations } from '@/test/a11y';
import { MockEventSource } from '@/test/eventSource';
import { makeBankMe, makeCompanyChoice, makeMe, problemResponse } from '@/test/factories';
import { renderApp } from '@/test/render';
import { mockSessions } from '@/test/sessions';
import { server } from '@/test/server';
import { appRoutes } from './router';
import {
  errorTexts,
  fill,
  guards,
  home as homeText,
  loginPlaceholder,
  placeholders,
  shell,
} from '@/texts';

const banner = () => screen.getByTestId('demo-banner');

async function expectNoBlockingViolations(container: HTMLElement) {
  expect(await blockingA11yViolations(container)).toEqual([]);
}

describe('оболочка клиента', () => {
  it('показывает шапку, постоянную демо-плашку, меню, компанию и подвал', async () => {
    mockSessions({ client: makeMe() });
    const { container } = renderApp('/');

    expect(
      await screen.findByRole('heading', { level: 1, name: homeText.title }),
    ).toBeInTheDocument();
    expect(banner()).toHaveTextContent(shell.demoBanner);
    expect(screen.getByRole('link', { name: shell.productName })).toBeInTheDocument();
    const nav = screen.getByRole('navigation', { name: shell.mainNavLabel });
    expect(within(nav).getByRole('link', { name: shell.nav.loans })).toBeInTheDocument();
    expect(screen.getByText('ООО «Ромашка»')).toBeInTheDocument();
    expect(
      screen.getByText(fill(shell.user.signedInAs, { name: 'Анна Соколова' })),
    ).toBeInTheDocument();
    expect(screen.getByTestId('app-footer')).toHaveTextContent(shell.footer);
    // зона клиента не похожа на банк: полосы нет
    expect(screen.queryByTestId('zone-strip')).not.toBeInTheDocument();
    expect(screen.queryByText(shell.bankZoneLabel)).not.toBeInTheDocument();
    expect(document.title).toContain(homeText.title);

    await expectNoBlockingViolations(container);
  });

  it('нет названия и логотипа банка', async () => {
    mockSessions({ client: makeMe() });
    renderApp('/');
    await screen.findByRole('heading', { level: 1 });
    expect(document.body.textContent).not.toMatch(/альфа/i);
    expect(document.querySelector('img')).toBeNull();
  });

  it('при нескольких компаниях предлагает сменить компанию', async () => {
    mockSessions({
      client: makeMe({
        companies: [
          makeCompanyChoice({ id: 'c1' }),
          makeCompanyChoice({ id: 'c2', inn: '7707083894', name: 'ИП Иванов' }),
        ],
        activeCompanyId: 'c2',
      }),
    });
    renderApp('/');
    expect(await screen.findByText('ИП Иванов')).toBeInTheDocument();
    expect(screen.getByRole('link', { name: shell.changeCompany })).toHaveAttribute(
      'href',
      '/company',
    );
  });

  it('карта адресов клиента: страницы открываются', async () => {
    mockSessions({ client: makeMe() });
    const paths = [
      ['/wizard', placeholders.wizard.title],
      ['/products/overdraft', placeholders.product.title],
      ['/applications/a1/offer', placeholders.offer.title],
      ['/applications/a1/sign', placeholders.sign.title],
      ['/loans/l1', placeholders.loan.title],
      ['/notifications', placeholders.notifications.title],
    ] as const;
    for (const [path, title] of paths) {
      const { unmount } = renderApp(path);
      expect(await screen.findByRole('heading', { level: 1, name: title })).toBeInTheDocument();
      unmount();
    }
  });
});

describe('вход и защита маршрутов', () => {
  it('без сессии отправляет на /login и запоминает адрес', async () => {
    renderApp('/loans');
    expect(
      await screen.findByRole('heading', { level: 1, name: loginPlaceholder.zoneClient }),
    ).toBeInTheDocument();
    expect(window.location.pathname).toBe('/login');
    expect(new URLSearchParams(window.location.search).get('next')).toBe('/loans');
    expect(banner()).toBeInTheDocument();
  });

  it('401 или 404 от /me — просто «не вошли», без экрана ошибки', async () => {
    server.use(http.get('*/api/me', () => problemResponse({ status: 404, code: 'NOT_FOUND' })));
    renderApp('/');
    expect(
      await screen.findByRole('heading', { level: 1, name: loginPlaceholder.zoneClient }),
    ).toBeInTheDocument();
    expect(screen.queryByTestId('error-screen')).not.toBeInTheDocument();
  });

  it('клиент по /bank видит объяснение, а не тихий переход', async () => {
    mockSessions({ client: makeMe() });
    renderApp('/bank');
    expect(
      await screen.findByRole('heading', { level: 1, name: guards.bankOnly.title }),
    ).toBeInTheDocument();
    expect(window.location.pathname).toBe('/bank');
    expect(screen.getByText(guards.bankOnly.body)).toBeInTheDocument();
    expect(screen.getByRole('link', { name: shell.common.back })).toHaveAttribute('href', '/');
    expect(screen.getByRole('link', { name: loginPlaceholder.bankLink })).toBeInTheDocument();
    expect(banner()).toBeInTheDocument();
  });

  it('без сессий на /bank ведёт на вход банка', async () => {
    renderApp('/bank');
    expect(
      await screen.findByRole('heading', { level: 1, name: loginPlaceholder.zoneBank }),
    ).toBeInTheDocument();
    const params = new URLSearchParams(window.location.search);
    expect(params.get('zone')).toBe('bank');
    expect(params.get('next')).toBe('/bank');
  });

  it('пользователь с ролью клиента в банковской сессии тоже видит объяснение', async () => {
    mockSessions({ bank: makeMe({ role: 'CLIENT' }) });
    renderApp('/bank');
    expect(
      await screen.findByRole('heading', { level: 1, name: guards.bankOnly.title }),
    ).toBeInTheDocument();
  });

  it('сотрудник банка в клиентской зоне видит объяснение', async () => {
    mockSessions({ client: makeBankMe('UNDERWRITER') });
    renderApp('/');
    expect(
      await screen.findByRole('heading', { level: 1, name: guards.clientOnly.title }),
    ).toBeInTheDocument();
  });

  it('поручитель попадает только на экран поручителя', async () => {
    mockSessions({ client: makeMe({ role: 'GUARANTOR' }) });
    renderApp('/loans');
    expect(
      await screen.findByRole('heading', { level: 1, name: placeholders.guarantee.title }),
    ).toBeInTheDocument();
    expect(window.location.pathname).toBe('/guarantee');
    const nav = screen.getByRole('navigation', { name: shell.mainNavLabel });
    expect(within(nav).queryAllByRole('link')).toHaveLength(0);
  });

  it('несуществующий адрес: «Не нашли такую страницу» в оболочке', async () => {
    mockSessions({ client: makeMe() });
    renderApp('/net-takoy-stranicy');
    expect(
      await screen.findByRole('heading', { level: 1, name: guards.pageNotFound.title }),
    ).toBeInTheDocument();
    expect(banner()).toBeInTheDocument();
    expect(screen.getByRole('navigation', { name: shell.mainNavLabel })).toBeInTheDocument();
  });

  it('сбой сервера на /me — отдельный экран с «Повторить», а не вход', async () => {
    server.use(
      http.get('*/api/me', () =>
        problemResponse({ status: 503, code: 'SERVICE_UNAVAILABLE', requestId: 'req-503' }),
      ),
    );
    renderApp('/');
    expect(
      await screen.findByRole('heading', { level: 1, name: guards.sessionCheckFailed.title }),
    ).toBeInTheDocument();
    expect(screen.getByText(errorTexts.SERVICE_UNAVAILABLE.text)).toBeInTheDocument();
    expect(screen.getByText(/req-503/)).toBeInTheDocument();

    mockSessions({ client: makeMe() });
    await userEvent.click(screen.getByRole('button', { name: shell.common.retry }));
    expect(
      await screen.findByRole('heading', { level: 1, name: homeText.title }),
    ).toBeInTheDocument();
  });

  it('401 посреди работы возвращает на вход', async () => {
    mockSessions({ client: makeMe() });
    const { queryClient } = renderApp('/');
    await screen.findByRole('heading', { level: 1, name: homeText.title });

    server.use(
      http.get('*/api/v1/tasks', () => problemResponse({ status: 401, code: 'UNAUTHENTICATED' })),
    );
    await act(async () => {
      await queryClient
        .fetchQuery({ queryKey: ['/api/v1/tasks'], queryFn: () => apiGet('/api/v1/tasks') })
        .catch(() => undefined);
    });
    expect(
      await screen.findByRole('heading', { level: 1, name: loginPlaceholder.zoneClient }),
    ).toBeInTheDocument();
    expect(window.location.pathname).toBe('/login');
  });
});

describe('две независимые сессии', () => {
  it('вкладки обеих зон живут вместе: банк не ломает клиента', async () => {
    mockSessions({ client: makeMe(), bank: makeBankMe('ADMIN') });

    const bank = renderApp('/bank');
    expect(
      await screen.findByRole('heading', { level: 1, name: placeholders.bankQueue.title }),
    ).toBeInTheDocument();
    bank.unmount();

    renderApp('/');
    expect(
      await screen.findByRole('heading', { level: 1, name: homeText.title }),
    ).toBeInTheDocument();
  });
});

describe('зона банка', () => {
  it('другая цветовая полоса, подпись и очередь; код зоны — отдельным куском', async () => {
    mockSessions({ bank: makeBankMe('UNDERWRITER') });
    const { container } = renderApp('/bank');

    expect(
      await screen.findByRole('heading', { level: 1, name: placeholders.bankQueue.title }),
    ).toBeInTheDocument();
    const strip = screen.getByTestId('zone-strip');
    expect(strip).toHaveTextContent(shell.bankZoneLabel);
    expect(banner()).toHaveTextContent(shell.demoBanner);
    expect(
      screen.getByText(fill(shell.user.signedInAs, { name: 'Ольга Петрова' })),
    ).toBeInTheDocument();
    expect(screen.queryByRole('link', { name: shell.nav.loans })).not.toBeInTheDocument();

    await expectNoBlockingViolations(container);
  });

  it('открывает карточку заявки банка', async () => {
    mockSessions({ bank: makeBankMe('UNDERWRITER') });
    renderApp('/bank/applications/a-1');
    expect(
      await screen.findByRole('heading', { level: 1, name: placeholders.bankApplication.title }),
    ).toBeInTheDocument();
  });

  it('зоны банка и демо подгружаются отдельными кусками (lazy)', () => {
    const root = appRoutes[0]?.children?.[0]?.children ?? [];
    const bank = root.find((route) => route.path === '/bank');
    const demo = root.find((route) => route.path === '/demo');
    expect(bank?.children?.[0]?.lazy).toBeTypeOf('function');
    expect(demo?.children?.[0]?.lazy).toBeTypeOf('function');
  });
});

describe('демо', () => {
  it('при выключенном демо нет ни пункта меню, ни адреса', async () => {
    mockSessions({ client: makeMe(), config: { demoMode: false } });
    const home = renderApp('/');
    await screen.findByRole('heading', { level: 1, name: homeText.title });
    expect(screen.queryByRole('link', { name: shell.nav.demo })).not.toBeInTheDocument();
    home.unmount();

    const demo = renderApp('/demo');
    expect(
      await screen.findByRole('heading', { level: 1, name: guards.demoNotFound.title }),
    ).toBeInTheDocument();
    expect(banner()).toBeInTheDocument();
    demo.unmount();
  });

  it('при включённом демо панель открывается без входа, пункт меню есть', async () => {
    mockSessions({ config: { demoMode: true } });
    const { container } = renderApp('/demo');
    expect(
      await screen.findByRole('heading', { level: 1, name: placeholders.demo.title }),
    ).toBeInTheDocument();
    expect(screen.getByTestId('zone-strip')).toHaveTextContent(shell.demoZoneLabel);
    await expectNoBlockingViolations(container);
  });

  it('пункт «Демо-панель» в меню клиента при включённом демо', async () => {
    mockSessions({ client: makeMe(), config: { demoMode: true } });
    renderApp('/');
    expect(await screen.findByRole('link', { name: shell.nav.demo })).toHaveAttribute(
      'href',
      '/demo',
    );
  });
});

describe('плашка «Демо-прототип» везде', () => {
  it.each([
    ['вход', '/login'],
    ['вход банка', '/login?zone=bank'],
    ['404', '/net-takoy-stranicy'],
  ])('%s', async (_name, route) => {
    renderApp(route);
    await screen.findByRole('heading', { level: 1 });
    expect(banner()).toHaveTextContent(shell.demoBanner);
  });
});

describe('вход (заглушка)', () => {
  it('после auth_expired показывает «Сессия закончилась»', async () => {
    mockSessions({ client: makeMe() });
    renderApp('/loans');
    await screen.findByRole('heading', { level: 1, name: placeholders.loans.title });
    await waitFor(() => expect(MockEventSource.instances.length).toBe(1));

    act(() => MockEventSource.latest().emit('auth_expired', {}));
    expect(
      await screen.findByRole('heading', { level: 1, name: loginPlaceholder.zoneClient }),
    ).toBeInTheDocument();
    expect(screen.getByText(loginPlaceholder.expired)).toBeInTheDocument();
    expect(window.location.pathname).toBe('/login');
    expect(new URLSearchParams(window.location.search).get('next')).toBe('/loans');
  });

  it('без экрана входа нет утечки на внешние адреса из next', async () => {
    renderApp('/login?next=https://evil.example/');
    expect(
      await screen.findByRole('heading', { level: 1, name: loginPlaceholder.zoneClient }),
    ).toBeInTheDocument();
  });

  it('доступность экрана входа', async () => {
    const { container } = renderApp('/login');
    await screen.findByRole('heading', { level: 1 });
    await expectNoBlockingViolations(container);
  });
});

describe('индикатор связи', () => {
  it('показывает три состояния', async () => {
    mockSessions({ client: makeMe() });
    renderApp('/');
    await screen.findByRole('heading', { level: 1, name: homeText.title });
    await waitFor(() => expect(MockEventSource.instances.length).toBe(1));
    const indicator = screen.getByTestId('connection-indicator');
    expect(indicator).toHaveAttribute('role', 'status');
    expect(indicator).toHaveTextContent('');

    act(() => MockEventSource.latest().open());
    expect(indicator).toHaveTextContent(shell.connection.connected);

    act(() => MockEventSource.latest().fail());
    expect(indicator).toHaveTextContent(shell.connection.reconnecting);

    act(() => MockEventSource.latest().fail());
    act(() => MockEventSource.latest().fail());
    expect(indicator).toHaveTextContent(shell.connection.polling);
  });

  it('поток открывается с зоной банка на адресах банка', async () => {
    mockSessions({ bank: makeBankMe() });
    renderApp('/bank');
    await screen.findByRole('heading', { level: 1, name: placeholders.bankQueue.title });
    await waitFor(() => expect(MockEventSource.instances.length).toBeGreaterThan(0));
    expect(MockEventSource.latest().url).toContain('zone=bank');
  });

  it('без сессии поток не открывается', async () => {
    renderApp('/login');
    await screen.findByRole('heading', { level: 1 });
    expect(MockEventSource.instances).toHaveLength(0);
  });
});

describe('нет связи', () => {
  it('тонкая полоса «Нет связи», пока сети нет', async () => {
    mockSessions({ client: makeMe() });
    renderApp('/');
    await screen.findByRole('heading', { level: 1, name: homeText.title });
    expect(screen.queryByTestId('offline-bar')).not.toBeInTheDocument();

    const spy = Object.getOwnPropertyDescriptor(Navigator.prototype, 'onLine');
    Object.defineProperty(Navigator.prototype, 'onLine', { configurable: true, get: () => false });
    act(() => {
      window.dispatchEvent(new Event('offline'));
    });
    expect(await screen.findByTestId('offline-bar')).toHaveTextContent(shell.offlineBar);

    Object.defineProperty(Navigator.prototype, 'onLine', { configurable: true, get: () => true });
    act(() => {
      window.dispatchEvent(new Event('online'));
    });
    await waitFor(() => expect(screen.queryByTestId('offline-bar')).not.toBeInTheDocument());
    if (spy) Object.defineProperty(Navigator.prototype, 'onLine', spy);
  });
});
