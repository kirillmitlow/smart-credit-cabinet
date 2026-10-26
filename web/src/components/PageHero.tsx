import type { ReactNode } from 'react';
import { Box } from '@mantine/core';
import { tokens } from '@/app/theme';

/**
 * Тёмная полоса под шапкой (D-113): продолжает графитовую шапку на всю ширину окна.
 * Фон тянется за края контейнера тенью и обрезается по бокам, поэтому горизонтальной прокрутки нет.
 */
export function PageHero({ children }: { children: ReactNode }) {
  const { header } = tokens;
  return (
    <Box
      data-testid="page-hero"
      mt="calc(-1 * var(--mantine-spacing-lg))"
      pt="lg"
      pb={36}
      style={{
        background: header.background,
        color: header.color,
        boxShadow: `0 0 0 100vmax ${header.background}`,
        clipPath: 'inset(0 -100vmax)',
      }}
    >
      {children}
    </Box>
  );
}
