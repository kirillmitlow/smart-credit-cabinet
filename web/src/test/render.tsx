import type { ReactElement } from 'react';
import { MantineProvider } from '@mantine/core';
import { QueryClientProvider, type QueryClient } from '@tanstack/react-query';
import { render, type RenderResult } from '@testing-library/react';
import { RouterProvider, createBrowserRouter } from 'react-router';
import { createQueryClient } from '@/api/query-client';
import { AppProviders } from '@/app/AppProviders';
import { appRoutes } from '@/app/router';
import { theme } from '@/app/theme';

/** Клиент запросов для тестов: без повторов и задержек, но с теми же обработчиками ошибок, что в приложении */
export function createTestQueryClient(): QueryClient {
  const client = createQueryClient();
  client.setDefaultOptions({
    queries: { retry: false, staleTime: 0, gcTime: Infinity },
    mutations: { retry: false },
  });
  return client;
}

export interface RenderAppResult extends RenderResult {
  queryClient: QueryClient;
}

/** Всё приложение целиком по адресу `route`: тема, кэш, маршруты, защита, корневая раскладка */
export function renderApp(route = '/', queryClient = createTestQueryClient()): RenderAppResult {
  window.history.pushState({}, '', route);
  const router = createBrowserRouter(appRoutes);
  const result = render(
    <AppProviders queryClient={queryClient}>
      <RouterProvider router={router} />
    </AppProviders>,
  );
  return Object.assign(result, { queryClient });
}

/**
 * Всё приложение по адресу `route` с состоянием перехода (`navigate(to, { state })`): так на экран
 * попадают данные, которые другой экран передал через адрес (например, результат мастера подбора).
 */
export function renderAppWithState(
  route: string,
  state: unknown,
  queryClient = createTestQueryClient(),
): RenderAppResult {
  window.history.pushState({ usr: state, key: 'test-key', idx: 1 }, '', route);
  const router = createBrowserRouter(appRoutes);
  const result = render(
    <AppProviders queryClient={queryClient}>
      <RouterProvider router={router} />
    </AppProviders>,
  );
  return Object.assign(result, { queryClient });
}

/** Отдельный компонент или хук внутри темы и кэша (без маршрутов) */
export function renderWithProviders(
  ui: ReactElement,
  queryClient = createTestQueryClient(),
): RenderAppResult {
  const result = render(
    <MantineProvider theme={theme} forceColorScheme="light">
      <QueryClientProvider client={queryClient}>{ui}</QueryClientProvider>
    </MantineProvider>,
  );
  return Object.assign(result, { queryClient });
}
