import { useState } from 'react';
import { Button, Center, Group, Loader, Stack, Text, Title } from '@mantine/core';
import { useQueryClient } from '@tanstack/react-query';
import { useNavigate } from 'react-router';
import { useGetLoginRoles, useRequestLoginCode } from '@/api/generated/api';
import type { CodeIssued, MeResponse } from '@/api/generated/model';
import { sessionQueryKey } from '@/api/session-keys';
import { isAppError } from '@/api/errors';
import { ProblemAlert } from '@/components/ProblemAlert';
import { login } from '@/texts';
import { CodeStep } from './CodeStep';
import { InnStep } from './InnStep';
import { NotEligible } from './NotEligible';
import { WhoStep, type LoginChoice } from './WhoStep';
import { usePublicConfig } from './session';
import { useFocusOnMount } from './useFocusOnMount';

type Stage =
  | { name: 'inn'; inn: string }
  | { name: 'who'; inn: string }
  | { name: 'code'; inn: string; choice: LoginChoice; issued: CodeIssued; issuedAt: number };

/** Кэш с данными прошлого пользователя не переживает вход: остаются только настройки стенда и новая сессия */
function startSession(queryClient: ReturnType<typeof useQueryClient>, me: MeResponse) {
  queryClient.removeQueries({
    predicate: (query) => query.queryKey[0] !== 'session' && query.queryKey[0] !== 'public-config',
  });
  queryClient.setQueryData(sessionQueryKey('client'), me);
}

/**
 * Вход клиента (D-062, 60-03 №1): ИНН → кто входит → код → кабинет. Всё, что про способ входа,
 * живёт в `features/auth`; результат один: сессия создана и `GET /me` отвечает.
 */
export function ClientLogin({ next }: { next: string | null }) {
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const config = usePublicConfig();
  const [stage, setStage] = useState<Stage>({ name: 'inn', inn: '' });
  const requestCode = useRequestLoginCode();
  const failureHeading = useFocusOnMount<HTMLHeadingElement>();
  const innForRoles = stage.name === 'inn' ? '' : stage.inn;
  const roles = useGetLoginRoles(innForRoles, {
    query: { enabled: innForRoles !== '', retry: false },
  });

  const issue = (choice: LoginChoice, inn: string) => {
    requestCode.mutate(
      { data: { userId: choice.userId, companyId: choice.companyId } },
      {
        onSuccess: (response) => {
          if (response.status !== 200) return;
          setStage({ name: 'code', inn, choice, issued: response.data, issuedAt: Date.now() });
        },
      },
    );
  };

  const onLoggedIn = (me: MeResponse) => {
    startSession(queryClient, me);
    const needsCompany = me.activeCompanyId === null && me.companies.length > 1;
    const target = next ?? '/';
    void navigate(needsCompany ? `/company?next=${encodeURIComponent(target)}` : target, {
      replace: true,
    });
  };

  if (stage.name === 'inn') {
    return (
      <InnStep
        initialInn={stage.inn}
        showUnderwriter={config.data?.demoMode === true}
        onSubmit={(inn) => {
          requestCode.reset();
          setStage({ name: 'who', inn });
        }}
      />
    );
  }

  const back = () => {
    requestCode.reset();
    setStage({ name: 'inn', inn: stage.inn });
  };

  if (stage.name === 'who') {
    if (roles.isPending) {
      return (
        <Center py="xl" role="status">
          <Stack align="center" gap="xs">
            <Loader size="sm" />
            <Text size="sm" c="dimmed">
              {login.innStep.checking}
            </Text>
          </Stack>
        </Center>
      );
    }
    if (roles.isError || roles.data?.status !== 200) {
      const rejected =
        isAppError(roles.error) &&
        (roles.error.code === 'INN_NOT_FOUND' || roles.error.code === 'INN_INVALID');
      if (rejected) {
        // ИНН не подошёл: остаёмся на первом шаге с пояснением под полем
        return (
          <InnStep
            key={roles.errorUpdatedAt}
            initialInn={stage.inn}
            serverError={roles.error}
            showUnderwriter={config.data?.demoMode === true}
            onSubmit={(inn) => {
              if (inn === stage.inn) void roles.refetch();
              else setStage({ name: 'who', inn });
            }}
          />
        );
      }
      return (
        <Stack gap="md">
          <Title order={2} size="h3" ref={failureHeading} tabIndex={-1}>
            {login.whoStep.heading}
          </Title>
          <ProblemAlert
            error={roles.error}
            onAction={() => {
              void roles.refetch();
            }}
          />
          <Group>
            <Button variant="default" onClick={back}>
              {login.whoStep.back}
            </Button>
          </Group>
        </Stack>
      );
    }
    const data = roles.data.data;
    if (data.kind === 'NOT_ELIGIBLE') return <NotEligible onBack={back} />;
    return (
      <WhoStep
        roles={data}
        pending={requestCode.isPending}
        error={requestCode.error}
        onSubmit={(choice) => issue(choice, stage.inn)}
        onBack={back}
      />
    );
  }

  return (
    <CodeStep
      key={stage.issued.requestId}
      choice={stage.choice}
      issued={stage.issued}
      issuedAt={stage.issuedAt}
      requestingNew={requestCode.isPending}
      newCodeError={requestCode.error}
      onNewCode={() => issue(stage.choice, stage.inn)}
      onBack={() => {
        requestCode.reset();
        setStage({ name: 'who', inn: stage.inn });
      }}
      onLoggedIn={onLoggedIn}
    />
  );
}
