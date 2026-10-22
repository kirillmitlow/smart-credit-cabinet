import { Button, Center, Loader, Stack, Text } from '@mantine/core';
import { Link, isRouteErrorResponse, useLocation, useRouteError } from 'react-router';
import { isAppError } from '@/api/errors';
import { ErrorScreen } from '@/components/ErrorScreen';
import { usePageHeading } from '@/lib/usePageHeading';
import { errorView, guards, loginPlaceholder, shell } from '@/texts';

/** Ожидание проверки входа: не белый экран, а явная подпись */
export function Splash() {
  return (
    <Center py="xl" role="status">
      <Stack align="center" gap="xs">
        <Loader size="sm" />
        <Text size="sm" c="dimmed">
          {guards.checkingSession}
        </Text>
      </Stack>
    </Center>
  );
}

type NotFoundKind = 'page' | 'application' | 'demo';

const notFoundTexts = {
  page: guards.pageNotFound,
  application: guards.applicationNotFound,
  demo: guards.demoNotFound,
} as const;

/** «Не нашли такую страницу / заявку» (`404`), «Не найдено» для выключенного демо */
export function NotFoundScreen({ kind = 'page' }: { kind?: NotFoundKind }) {
  const text = notFoundTexts[kind];
  usePageHeading(text.title);
  return (
    <ErrorScreen
      title={text.title}
      body={text.body}
      actions={
        <Button component={Link} to="/" variant="light">
          {shell.common.toHome}
        </Button>
      }
    />
  );
}

/** Клиент зашёл на `/bank`: объясняем, что произошло, а не тихо перенаправляем (60-01) */
export function BankOnlyScreen({ loginHref }: { loginHref: string }) {
  return (
    <ErrorScreen
      title={guards.bankOnly.title}
      body={guards.bankOnly.body}
      actions={
        <>
          <Button component={Link} to="/" variant="light">
            {shell.common.back}
          </Button>
          <Button component={Link} to={loginHref} variant="subtle">
            {loginPlaceholder.bankLink}
          </Button>
        </>
      }
    />
  );
}

export function ClientOnlyScreen() {
  return (
    <ErrorScreen
      title={guards.clientOnly.title}
      body={guards.clientOnly.body}
      actions={
        <Button component={Link} to="/bank" variant="light">
          {shell.common.back}
        </Button>
      }
    />
  );
}

/** Сервер не ответил на `GET /me` (не `401`/`404`): отдельное состояние с «Повторить» */
export function SessionCheckFailed({ error, onRetry }: { error: unknown; onRetry: () => void }) {
  const view = errorView(error);
  return (
    <ErrorScreen
      title={guards.sessionCheckFailed.title}
      body={view.text}
      requestId={view.requestId}
      onRetry={onRetry}
    />
  );
}

/** Ошибка маршрута (отрисовки, загрузки куска кода, 404 из запроса): всегда с демо-плашкой выше */
export function RouteErrorScreen() {
  const error = useRouteError();
  const location = useLocation();

  if (isRouteErrorResponse(error) && error.status === 404) {
    return <NotFoundScreen />;
  }
  if (isAppError(error) && error.status === 404) {
    const isApplication = /\/applications\//.test(location.pathname);
    return <NotFoundScreen kind={isApplication ? 'application' : 'page'} />;
  }
  const view = errorView(error);
  return (
    <ErrorScreen
      title={guards.generalError.title}
      body={view.text}
      requestId={view.requestId}
      onRetry={() => {
        window.location.reload();
      }}
    />
  );
}
