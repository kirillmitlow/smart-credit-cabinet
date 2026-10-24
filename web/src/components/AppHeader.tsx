import type { ReactNode } from 'react';
import { Anchor, Box, Button, Group, Text } from '@mantine/core';
import { Link, NavLink } from 'react-router';
import { tokens } from '@/app/theme';
import type { Zone } from '@/api/zone';
import { ConnectionIndicator } from '@/components/ConnectionIndicator';
import { fill, logout, shell } from '@/texts';

export interface NavItem {
  to: string;
  label: string;
  end?: boolean;
}

export interface AppHeaderProps {
  zone: Zone | 'demo';
  nav: readonly NavItem[];
  homeHref: string;
  userName?: string | null;
  companyName?: string | null;
  /** Показать «Сменить компанию» (у пользователя их больше одной) */
  canSwitchCompany?: boolean;
  /** Место под колокольчик уведомлений (T-428) */
  notifications?: ReactNode;
  /** Кнопка «Выйти»: есть, когда у зоны уже есть способ выйти */
  onLogout?: () => void;
}

/**
 * Шапка: название продукта, меню, компания, место под колокольчик, индикатор связи.
 * В зоне банка сверху цветная полоса и подпись «Рабочее место банка (демо)»: зоны не спутать (D-085).
 */
export function AppHeader({
  zone,
  nav,
  homeHref,
  userName,
  companyName,
  canSwitchCompany = false,
  notifications,
  onLogout,
}: AppHeaderProps) {
  const strip =
    zone === 'bank'
      ? { ...tokens.bankStrip, label: shell.bankZoneLabel }
      : zone === 'demo'
        ? { ...tokens.demoStrip, label: shell.demoZoneLabel }
        : null;
  return (
    <Box component="header" data-zone={zone} style={{ borderBottom: '1px solid #dee2e6' }}>
      {strip ? (
        <Box
          data-testid="zone-strip"
          px="md"
          py={4}
          style={{ background: strip.background, color: strip.color }}
        >
          <Text size="sm" fw={600} c="inherit">
            {strip.label}
          </Text>
        </Box>
      ) : null}
      <Group justify="space-between" align="center" px="md" py="sm" mih={64} wrap="wrap">
        <Group gap="xl" wrap="wrap" miw={0}>
          <Anchor component={Link} to={homeHref} fw={700} fz="lg" underline="never" c="dark">
            {shell.productName}
          </Anchor>
          <Box component="nav" aria-label={shell.mainNavLabel}>
            <Group gap="md" component="ul" p={0} m={0} style={{ listStyle: 'none' }}>
              {nav.map((item) => (
                <li key={item.to}>
                  <Anchor component={NavLink} to={item.to} end={item.end} size="sm" fw={500}>
                    {item.label}
                  </Anchor>
                </li>
              ))}
            </Group>
          </Box>
        </Group>
        <Group gap="md" wrap="wrap" miw={0} maw="100%">
          {companyName ? (
            <Group gap="xs" wrap="wrap" miw={0} maw="100%">
              <Text size="sm" fw={500} style={{ overflowWrap: 'anywhere' }}>
                {companyName}
              </Text>
              {canSwitchCompany ? (
                <Anchor component={Link} to="/company" size="sm">
                  {shell.changeCompany}
                </Anchor>
              ) : null}
            </Group>
          ) : null}
          {notifications}
          {userName ? (
            <Text size="sm" c="dimmed" style={{ overflowWrap: 'anywhere' }}>
              {fill(shell.user.signedInAs, { name: userName })}
            </Text>
          ) : null}
          {onLogout ? (
            <Button variant="subtle" size="compact-sm" onClick={onLogout}>
              {logout.action}
            </Button>
          ) : null}
          <ConnectionIndicator />
        </Group>
      </Group>
    </Box>
  );
}
