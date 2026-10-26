import type { ReactNode } from 'react';
import { Group, Paper, Stack, Title } from '@mantine/core';

/** Белая карточка-раздел с заголовком h2 (D-113): основной строительный блок экранов */
export function SectionCard({
  id,
  title,
  aside,
  children,
  testId,
}: {
  id: string;
  title: string;
  /** Справа от заголовка: счётчик, ссылка, подпись */
  aside?: ReactNode;
  children: ReactNode;
  testId?: string;
}) {
  return (
    <Paper component="section" aria-labelledby={id} p={28} data-testid={testId} h="100%">
      <Stack gap="md" h="100%">
        <Group justify="space-between" align="baseline" gap="sm" wrap="wrap">
          <Title order={2} size="h3" id={id}>
            {title}
          </Title>
          {aside}
        </Group>
        {children}
      </Stack>
    </Paper>
  );
}
