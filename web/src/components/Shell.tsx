import type { ReactNode } from 'react';
import { Box, Container } from '@mantine/core';
import { ActiveFailureStrip } from '@/components/ActiveFailureStrip';
import { AppFooter } from '@/components/AppFooter';
import { AppHeader, type AppHeaderProps } from '@/components/AppHeader';

export interface ShellProps extends AppHeaderProps {
  children: ReactNode;
  /** Включённые демо-сбои для полосы под шапкой (наполняет T-435) */
  failures?: readonly string[];
}

/** Оболочка зоны: шапка, полоса сбоя, содержимое, подвал. Демо-плашка живёт выше, в корневой раскладке */
export function Shell({ children, failures, ...header }: ShellProps) {
  return (
    <Box>
      <AppHeader {...header} />
      <ActiveFailureStrip failures={failures ?? []} />
      <Container size="xl" component="main" id="main" tabIndex={-1} py="lg">
        {children}
      </Container>
      <AppFooter />
    </Box>
  );
}
