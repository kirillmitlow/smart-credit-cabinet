import type { ReactNode } from 'react';
import { Anchor, Box, Button, Container, Group, Stack, Text } from '@mantine/core';
import { Link, NavLink } from 'react-router';
import { fonts, tokens } from '@/app/theme';
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

const zoneTagline = {
  client: shell.tagline.client,
  bank: shell.tagline.bank,
  demo: shell.tagline.demo,
} as const;

/** Квадратный знак бренда с буквой: один и тот же на входе и в шапке */
export function BrandMark({ size = 40 }: { size?: number }) {
  return (
    <Box
      aria-hidden="true"
      w={size}
      h={size}
      style={{
        flex: 'none',
        borderRadius: size * 0.3,
        background: tokens.demoBanner.badge,
        color: '#ffffff',
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'center',
        fontFamily: fonts.display,
        fontWeight: 700,
        fontSize: size / 2,
      }}
    >
      {shell.brandLetter}
    </Box>
  );
}

/**
 * Тёмная шапка (D-113): знак и название, меню-«таблетки», компания и пользователь, «Выйти».
 * В зоне банка под шапкой цветная полоса «Рабочее место банка (демо)»: зоны не спутать (D-085).
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
  const { header } = tokens;
  return (
    <Box
      component="header"
      data-zone={zone}
      style={{ background: header.background, color: header.color }}
    >
      <Container size="xl">
        <Group justify="space-between" align="center" py="sm" mih={72} wrap="wrap" gap="lg">
          <Group gap="xl" wrap="wrap" miw={0}>
            <Anchor
              component={Link}
              to={homeHref}
              aria-label={shell.productName}
              underline="never"
              c="inherit"
              style={{ display: 'flex', alignItems: 'center', gap: 12 }}
            >
              <BrandMark />
              <Stack gap={0}>
                <Text ff={fonts.display} fw={700} fz={18} lh={1.25} c="inherit">
                  {shell.productName}
                </Text>
                <Text fz={13} lh={1.3} style={{ color: header.muted }}>
                  {zoneTagline[zone]}
                </Text>
              </Stack>
            </Anchor>
            {nav.length > 0 ? (
              <Box component="nav" aria-label={shell.mainNavLabel} className="scc-nav">
                <Group gap={4} component="ul" p={0} m={0} style={{ listStyle: 'none' }}>
                  {nav.map((item) => (
                    <li key={item.to}>
                      <NavLink to={item.to} end={item.end}>
                        {item.label}
                      </NavLink>
                    </li>
                  ))}
                </Group>
              </Box>
            ) : null}
          </Group>
          <Group gap="md" wrap="wrap" miw={0} maw="100%">
            {notifications}
            {companyName || userName ? (
              <Stack gap={2} align="flex-end" miw={0} maw={360}>
                {companyName ? (
                  <Text
                    fz={14}
                    fw={700}
                    ta="right"
                    c="inherit"
                    style={{ overflowWrap: 'anywhere' }}
                  >
                    {companyName}
                  </Text>
                ) : null}
                {userName ? (
                  <Text
                    fz={13}
                    ta="right"
                    style={{ color: header.muted, overflowWrap: 'anywhere' }}
                  >
                    {fill(shell.user.signedInAs, { name: userName })}
                  </Text>
                ) : null}
                {canSwitchCompany ? (
                  <Anchor component={Link} to="/company" fz={13} style={{ color: header.color }}>
                    {shell.changeCompany}
                  </Anchor>
                ) : null}
                <ConnectionIndicator onDark />
              </Stack>
            ) : (
              <ConnectionIndicator onDark />
            )}
            {onLogout ? (
              <Button
                variant="outline"
                color="gray"
                onClick={onLogout}
                styles={{ root: { color: header.color, borderColor: header.border } }}
              >
                {logout.action}
              </Button>
            ) : null}
          </Group>
        </Group>
      </Container>
      {strip ? (
        <Box
          data-testid="zone-strip"
          py={4}
          style={{ background: strip.background, color: strip.color }}
        >
          <Container size="xl">
            <Text size="sm" fw={600} c="inherit">
              {strip.label}
            </Text>
          </Container>
        </Box>
      ) : null}
    </Box>
  );
}
