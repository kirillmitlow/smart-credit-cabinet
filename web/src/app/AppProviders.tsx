import type { ReactNode } from 'react';
import { MantineProvider } from '@mantine/core';
import { QueryClientProvider, type QueryClient } from '@tanstack/react-query';
import { AppErrorBoundary } from '@/components/AppErrorBoundary';
import { cssVariablesResolver, theme } from './theme';

/** Тема Mantine (светлая), кэш запросов и последний рубеж — граница ошибок отрисовки */
export function AppProviders({
  queryClient,
  children,
}: {
  queryClient: QueryClient;
  children: ReactNode;
}) {
  return (
    <MantineProvider
      theme={theme}
      cssVariablesResolver={cssVariablesResolver}
      defaultColorScheme="light"
      forceColorScheme="light"
    >
      <AppErrorBoundary>
        <QueryClientProvider client={queryClient}>{children}</QueryClientProvider>
      </AppErrorBoundary>
    </MantineProvider>
  );
}
