import { screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { RouterProvider, createMemoryRouter } from 'react-router';
import { MantineProvider } from '@mantine/core';
import { describe, expect, it, vi } from 'vitest';
import { AppError } from '@/api/errors';
import { RouteErrorScreen } from '@/app/screens';
import { theme } from '@/app/theme';
import { blockingA11yViolations } from '@/test/a11y';
import { renderWithProviders } from '@/test/render';
import { copySupportCode, errorTexts, fill, guards, shell, supportCodeLabel } from '@/texts';
import { ActiveFailureStrip } from './ActiveFailureStrip';
import { AppErrorBoundary } from './AppErrorBoundary';
import { DesktopHint } from './DesktopHint';
import { ErrorScreen } from './ErrorScreen';
import { ProblemAlert } from './ProblemAlert';

function Boom(): never {
  throw new Error('внутренняя поломка, которую человеку показывать нельзя');
}

describe('ProblemAlert', () => {
  it('показывает текст из словаря по code, а не detail', () => {
    const error = new AppError({
      code: 'VERSION_CONFLICT',
      status: 409,
      requestId: 'req-77',
      detail: 'stale row',
    });
    renderWithProviders(<ProblemAlert error={error} />);
    expect(screen.getByRole('alert')).toHaveTextContent(errorTexts.VERSION_CONFLICT.text);
    expect(screen.queryByText(/stale row/)).not.toBeInTheDocument();
    expect(screen.getByText(fill(supportCodeLabel, { requestId: 'req-77' }))).toBeInTheDocument();
  });

  it('кнопка действия из словаря вызывает обработчик', async () => {
    const onAction = vi.fn();
    const error = new AppError({ code: 'SERVICE_UNAVAILABLE', status: 503, requestId: 'r' });
    renderWithProviders(<ProblemAlert error={error} onAction={onAction} />);
    await userEvent.click(
      screen.getByRole('button', { name: errorTexts.SERVICE_UNAVAILABLE.action }),
    );
    expect(onAction).toHaveBeenCalledTimes(1);
  });

  it('неизвестный code: общий текст и номер запроса, приложение не падает', () => {
    const error = new AppError({ code: 'NEW_CODE_FROM_FUTURE', status: 500, requestId: 'req-x' });
    renderWithProviders(<ProblemAlert error={error} />);
    expect(screen.getByText(errorTexts.UNKNOWN_ERROR.text)).toBeInTheDocument();
    expect(screen.getByText(/req-x/)).toBeInTheDocument();
  });

  it('не AppError тоже превращается в общий текст', () => {
    renderWithProviders(<ProblemAlert error={new TypeError('x is undefined')} />);
    expect(screen.getByText(errorTexts.UNKNOWN_ERROR.text)).toBeInTheDocument();
    expect(screen.queryByText(/x is undefined/)).not.toBeInTheDocument();
  });
});

describe('ErrorScreen', () => {
  it('заголовок, «Повторить», код для поддержки и копирование', async () => {
    const onRetry = vi.fn();
    const { container } = renderWithProviders(
      <ErrorScreen
        title="Что-то случилось"
        body="Подробности"
        requestId="req-5"
        onRetry={onRetry}
      />,
    );
    const heading = screen.getByRole('heading', { level: 1, name: 'Что-то случилось' });
    expect(heading).toHaveFocus();
    await userEvent.click(screen.getByRole('button', { name: shell.common.retry }));
    expect(onRetry).toHaveBeenCalled();
    expect(screen.getByText(fill(supportCodeLabel, { requestId: 'req-5' }))).toBeInTheDocument();
    expect(screen.getByRole('button', { name: copySupportCode })).toBeInTheDocument();
    expect(await blockingA11yViolations(container)).toEqual([]);
  });

  it('без номера запроса строки «Код для поддержки» нет', () => {
    renderWithProviders(<ErrorScreen title="Пусто" />);
    expect(screen.queryByText(/Код для поддержки/)).not.toBeInTheDocument();
  });
});

describe('AppErrorBoundary', () => {
  it('ловит ошибку отрисовки: общий экран, «Повторить»', () => {
    const consoleError = vi.spyOn(console, 'error').mockImplementation(() => undefined);
    renderWithProviders(
      <AppErrorBoundary>
        <Boom />
      </AppErrorBoundary>,
    );
    expect(screen.queryByTestId('demo-banner')).not.toBeInTheDocument();
    expect(
      screen.getByRole('heading', { level: 1, name: guards.generalError.title }),
    ).toBeInTheDocument();
    expect(screen.getByText(errorTexts.UNKNOWN_ERROR.text)).toBeInTheDocument();
    expect(screen.queryByText(/внутренняя поломка/)).not.toBeInTheDocument();
    expect(screen.getByRole('button', { name: shell.common.retry })).toBeInTheDocument();
    expect(consoleError).toHaveBeenCalled();
  });
});

describe('RouteErrorScreen', () => {
  function renderRoute(path: string, error: unknown) {
    const router = createMemoryRouter(
      [
        {
          path: '/applications/:id',
          element: (
            <>
              <Thrower error={error} />
            </>
          ),
          errorElement: <RouteErrorScreen />,
        },
        { path: '/other', element: <Thrower error={error} />, errorElement: <RouteErrorScreen /> },
      ],
      { initialEntries: [path] },
    );
    return renderWithProvidersAndRouter(router);
  }

  function Thrower({ error }: { error: unknown }): never {
    throw error;
  }

  function renderWithProvidersAndRouter(router: ReturnType<typeof createMemoryRouter>) {
    vi.spyOn(console, 'error').mockImplementation(() => undefined);
    return renderWithProviders(
      <MantineProvider theme={theme}>
        <RouterProvider router={router} />
      </MantineProvider>,
    );
  }

  it('404 по заявке → «Не нашли такую заявку»', async () => {
    renderRoute(
      '/applications/zzz',
      new AppError({ code: 'NOT_FOUND', status: 404, requestId: 'r' }),
    );
    expect(
      await screen.findByRole('heading', { level: 1, name: guards.applicationNotFound.title }),
    ).toBeInTheDocument();
  });

  it('404 вне заявок → «Не нашли такую страницу»', async () => {
    renderRoute('/other', new AppError({ code: 'NOT_FOUND', status: 404, requestId: 'r' }));
    expect(
      await screen.findByRole('heading', { level: 1, name: guards.pageNotFound.title }),
    ).toBeInTheDocument();
  });

  it('прочая ошибка → общий экран с кодом для поддержки', async () => {
    renderRoute(
      '/other',
      new AppError({ code: 'SERVICE_UNAVAILABLE', status: 503, requestId: 'req-9' }),
    );
    expect(
      await screen.findByRole('heading', { level: 1, name: guards.generalError.title }),
    ).toBeInTheDocument();
    expect(screen.getByText(errorTexts.SERVICE_UNAVAILABLE.text)).toBeInTheDocument();
    expect(screen.getByText(/req-9/)).toBeInTheDocument();
  });

  it('обычное исключение → общий текст', async () => {
    renderRoute('/other', new Error('сломалось'));
    expect(await screen.findByText(errorTexts.UNKNOWN_ERROR.text)).toBeInTheDocument();
  });
});

describe('мелкие компоненты', () => {
  it('полоса сбоя пуста без сбоев и показывает активные', () => {
    const { rerender } = renderWithProviders(<ActiveFailureStrip />);
    expect(screen.queryByRole('status')).not.toBeInTheDocument();
    rerender(
      <MantineProvider theme={theme}>
        <ActiveFailureStrip failures={['БКИ недоступно']} />
      </MantineProvider>,
    );
    expect(screen.getByRole('status')).toHaveTextContent('БКИ недоступно');
  });

  it('подсказка про узкий экран есть в разметке (показывается стилем при ширине < 1280 px)', () => {
    renderWithProviders(<DesktopHint />);
    expect(screen.getByRole('note')).toHaveTextContent(shell.desktopHint);
  });
});
