import { Button, Center, Loader, Stack, Text } from '@mantine/core';
import { useQueryClient } from '@tanstack/react-query';
import { useNavigate } from 'react-router';
import { useBankDemoLogin } from '@/api/generated/api';
import { sessionQueryKey } from '@/api/session-keys';
import { ProblemAlert } from '@/components/ProblemAlert';
import { safeNext } from '@/features/auth/loginUrl';
import { usePublicConfig } from '@/features/auth/session';
import { bankLogin } from '@/texts/bank';

/** После входа возвращаем только в банковскую зону, включая нормализацию `..` и обратных слешей. */
function bankTarget(next: string | null): string {
  const candidate = safeNext(next);
  if (!candidate) return '/bank';
  try {
    const target = new URL(candidate, window.location.origin);
    if (
      target.origin === window.location.origin &&
      (target.pathname === '/bank' || target.pathname.startsWith('/bank/'))
    ) {
      return `${target.pathname}${target.search}${target.hash}`;
    }
  } catch {
    return '/bank';
  }
  return '/bank';
}

/** Демо-вход банка создаёт отдельную сессию, не затрагивая данные клиента (D-085, D-090). */
export function BankLogin({ next }: { next: string | null }) {
  const config = usePublicConfig();
  const queryClient = useQueryClient();
  const navigate = useNavigate();
  const login = useBankDemoLogin({
    mutation: {
      onSuccess: async (response) => {
        if (response.status !== 200) return;
        // Защита маршрута сразу видит новую сессию, даже если до входа в кэше был `null`.
        queryClient.setQueryData(sessionQueryKey('bank'), {
          ...response.data,
          activeCompanyId: null,
          companies: [],
        });
        await queryClient.invalidateQueries({ queryKey: sessionQueryKey('bank'), exact: true });
        void navigate(bankTarget(next), { replace: true });
      },
    },
  });

  if (config.isPending) {
    return (
      <Center py="md" role="status">
        <Stack align="center" gap="xs">
          <Loader size="sm" />
          <Text size="sm" c="dimmed">
            {bankLogin.checking}
          </Text>
        </Stack>
      </Center>
    );
  }

  if (config.isError) {
    return (
      <ProblemAlert
        error={config.error}
        onAction={() => {
          void config.refetch();
        }}
      />
    );
  }

  if (config.data.demoMode !== true) {
    return (
      <Stack gap="md">
        <Text role="status">{bankLogin.unavailable}</Text>
        <Button disabled>{bankLogin.submit}</Button>
      </Stack>
    );
  }

  const submit = () => {
    if (!login.isPending) login.mutate({ data: { role: 'UNDERWRITER' } });
  };

  return (
    <Stack gap="md">
      <Text>{bankLogin.body}</Text>
      {login.isError ? <ProblemAlert error={login.error} onAction={submit} /> : null}
      <Button onClick={submit} loading={login.isPending} disabled={login.isPending}>
        {login.isPending ? bankLogin.submitting : bankLogin.submit}
      </Button>
    </Stack>
  );
}
