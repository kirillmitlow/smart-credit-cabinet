import { Alert, Box, Group, Paper, Stack, Text, Title } from '@mantine/core';
import { useSearchParams } from 'react-router';
import { fonts, tokens } from '@/app/theme';
import { BrandMark } from '@/components/AppHeader';
import { usePageHeading } from '@/lib/usePageHeading';
import { login, loginPlaceholder, shell } from '@/texts';
import { BankLogin } from '@/features/bank/BankLogin';
import { ClientLogin } from './ClientLogin';
import { safeNext } from './loginUrl';

/** Тёмная панель слева: бренд, обещание продукта и честная пометка про демо (D-113) */
function LoginHero() {
  const { header } = tokens;
  return (
    <Stack
      component="section"
      aria-label={shell.productName}
      justify="space-between"
      gap={40}
      p={48}
      style={{ flex: '1 1 480px', background: header.background, color: header.color }}
    >
      <Group gap={12} wrap="nowrap">
        <BrandMark size={44} />
        <Stack gap={0}>
          <Text ff={fonts.display} fw={700} fz={20} c="inherit">
            {shell.productName}
          </Text>
          <Text fz={14} style={{ color: header.muted }}>
            {shell.tagline.client}
          </Text>
        </Stack>
      </Group>
      <Stack gap={32}>
        <Text ff={fonts.display} fw={700} fz={40} lh={1.15} c="inherit">
          {login.hero.title}
          <br />
          <Box component="span" style={{ color: tokens.accentOnDark }}>
            {login.hero.accent}
          </Box>
        </Text>
        <Stack component="ol" gap={16} m={0} p={0} style={{ listStyle: 'none' }}>
          {login.hero.points.map((point, index) => (
            <Group component="li" key={point} gap={14} wrap="nowrap" fz={17}>
              <Text component="span" fw={700} w={24} style={{ color: tokens.accentOnDark }}>
                {String(index + 1).padStart(2, '0')}
              </Text>
              <Text component="span" fz={17} style={{ color: '#e4e4e7' }}>
                {point}
              </Text>
            </Group>
          ))}
        </Stack>
      </Stack>
      <Text fz={13} style={{ color: header.muted }}>
        {login.hero.note}
      </Text>
    </Stack>
  );
}

/**
 * Страница входа (60-01, «Вход как сменный блок»). Клиент: ИНН → кто входит → код → кабинет
 * (`ClientLogin`). Банк входит отдельной демо-кнопкой и сохраняет собственную сессию (T-213).
 * Вид — две колонки: тёмная панель бренда и белая карточка шагов (D-113).
 */
export function LoginPage() {
  const [params] = useSearchParams();
  const isBank = params.get('zone') === 'bank';
  const expired = params.get('reason') === 'expired';
  const title = isBank ? loginPlaceholder.zoneBank : loginPlaceholder.zoneClient;
  const headingRef = usePageHeading(title);

  return (
    <Box style={{ display: 'flex', flexWrap: 'wrap', minHeight: '100vh' }}>
      <LoginHero />
      <Box
        component="main"
        id="main"
        tabIndex={-1}
        px="lg"
        py={48}
        style={{
          flex: '1 1 520px',
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'center',
        }}
      >
        <Paper p={36} w="100%" maw={480}>
          <Stack gap="md">
            <Title order={1} size="h2" ref={headingRef} tabIndex={-1}>
              {title}
            </Title>
            {expired ? (
              <Alert color="yellow" role="status">
                {loginPlaceholder.expired}
              </Alert>
            ) : null}
            {isBank ? (
              <BankLogin next={safeNext(params.get('next'))} />
            ) : (
              <ClientLogin next={safeNext(params.get('next'))} />
            )}
          </Stack>
        </Paper>
      </Box>
    </Box>
  );
}
