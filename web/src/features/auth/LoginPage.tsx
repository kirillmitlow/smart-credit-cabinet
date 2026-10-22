import { Alert, Container, Stack, Title } from '@mantine/core';
import { useSearchParams } from 'react-router';
import { AppFooter } from '@/components/AppFooter';
import { usePageHeading } from '@/lib/usePageHeading';
import { loginPlaceholder } from '@/texts';
import { BankLogin } from '@/features/bank/BankLogin';
import { ClientLogin } from './ClientLogin';
import { safeNext } from './loginUrl';

/**
 * Страница входа (60-01, «Вход как сменный блок»). Клиент: ИНН → кто входит → код → кабинет
 * (`ClientLogin`). Банк входит отдельной демо-кнопкой и сохраняет собственную сессию (T-213).
 */
export function LoginPage() {
  const [params] = useSearchParams();
  const isBank = params.get('zone') === 'bank';
  const expired = params.get('reason') === 'expired';
  const title = isBank ? loginPlaceholder.zoneBank : loginPlaceholder.zoneClient;
  const headingRef = usePageHeading(title);

  return (
    <>
      <Container size="xs" component="main" id="main" tabIndex={-1} py="xl">
        <Stack gap="md">
          <Title order={1} ref={headingRef} tabIndex={-1}>
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
      </Container>
      <AppFooter />
    </>
  );
}
