import { Alert, Anchor, Container, Stack, Text, Title } from '@mantine/core';
import { Link, useSearchParams } from 'react-router';
import { AppFooter } from '@/components/AppFooter';
import { usePageHeading } from '@/lib/usePageHeading';
import { loginPlaceholder } from '@/texts';

/**
 * Заглушка входа: сюда ведёт защита маршрутов, пока способа входа нет. Настоящий вход (ИНН + код, D-062)
 * целиком живёт в этой папке и заменяет только этот файл.
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
          <Text>{loginPlaceholder.body}</Text>
          {isBank ? (
            <Anchor component={Link} to="/login">
              {loginPlaceholder.clientLink}
            </Anchor>
          ) : (
            <Anchor component={Link} to="/login?zone=bank">
              {loginPlaceholder.bankLink}
            </Anchor>
          )}
        </Stack>
      </Container>
      <AppFooter />
    </>
  );
}
