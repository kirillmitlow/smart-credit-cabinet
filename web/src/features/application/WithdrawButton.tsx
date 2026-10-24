import { useRef, useState } from 'react';
import { Button, Group, Modal, Stack, Text } from '@mantine/core';
import { useDisclosure } from '@mantine/hooks';
import { useQueryClient } from '@tanstack/react-query';
import { getApplication, useWithdrawApplication } from '@/api/generated/api';
import type { ApplicationOut } from '@/api/generated/model';
import { useActionKey } from '@/api/idempotency';
import { ProblemAlert } from '@/components/ProblemAlert';
import { applicationPage } from '@/texts';
import { putApplication } from './useApplication';

export interface WithdrawButtonProps {
  application: ApplicationOut;
  /** Для одобренной заявки и встречных кнопка называется «Отказаться» (60-03) */
  asDecline?: boolean;
}

/** «Отозвать заявку» до подписания: необратимое действие, поэтому с подтверждением */
export function WithdrawButton({ application, asDecline = false }: WithdrawButtonProps) {
  const queryClient = useQueryClient();
  const [opened, { open, close }] = useDisclosure(false);
  const action = useActionKey();
  const withdraw = useWithdrawApplication({ request: action.request() });
  const submitting = useRef(false);
  const checking = useRef(false);
  const [refreshing, setRefreshing] = useState(false);
  const [refreshError, setRefreshError] = useState<unknown>(null);
  const [completed, setCompleted] = useState(false);
  const locked = withdraw.isPending || refreshing;

  const confirm = async () => {
    if (submitting.current || checking.current || withdraw.isError || completed) return;
    submitting.current = true;
    let succeeded = false;
    try {
      const response = await withdraw.mutateAsync({
        applicationId: application.id,
        data: { confirmed: true },
      });
      if (response.status !== 200) return;
      succeeded = true;
      setCompleted(true);
      action.reset();
      putApplication(queryClient, response.data);
      void queryClient.invalidateQueries({ queryKey: ['/applications'] });
      close();
    } catch {
      // A lost response can hide a committed withdrawal. Read state before allowing another POST.
    } finally {
      if (!succeeded) submitting.current = false;
    }
  };

  const checkState = async () => {
    if (checking.current || submitting.current) return;
    checking.current = true;
    setRefreshing(true);
    setRefreshError(null);
    try {
      const response = await getApplication(application.id);
      if (response.status !== 200) return;
      putApplication(queryClient, response.data);
      void queryClient.invalidateQueries({ queryKey: ['/applications'] });
      withdraw.reset();
      if (!response.data.allowedActions.includes('WITHDRAW')) {
        setCompleted(true);
        close();
      }
    } catch (error) {
      setRefreshError(error);
    } finally {
      checking.current = false;
      setRefreshing(false);
    }
  };

  const closeIdle = () => {
    if (!withdraw.isPending && !submitting.current && !checking.current) close();
  };

  return (
    <>
      <Button variant="subtle" color="gray" onClick={open} disabled={locked || completed}>
        {asDecline ? applicationPage.withdraw.decline : applicationPage.withdraw.action}
      </Button>
      <Modal
        opened={opened}
        onClose={closeIdle}
        title={applicationPage.withdraw.title}
        closeOnClickOutside={!locked}
        closeOnEscape={!locked}
        withCloseButton={!locked}
        aria-busy={locked}
      >
        <Stack>
          <Text>{applicationPage.withdraw.body}</Text>
          {locked ? (
            <Text role="status">
              {refreshing ? applicationPage.withdraw.checking : applicationPage.withdraw.pending}
            </Text>
          ) : null}
          {withdraw.isError ? (
            <>
              <ProblemAlert error={withdraw.error} />
              <Button variant="light" onClick={() => void checkState()} loading={refreshing}>
                {applicationPage.withdraw.checkState}
              </Button>
            </>
          ) : null}
          {refreshError ? <ProblemAlert error={refreshError} /> : null}
          <Group justify="flex-end">
            <Button variant="default" onClick={closeIdle} disabled={locked}>
              {applicationPage.withdraw.cancel}
            </Button>
            <Button
              onClick={() => void confirm()}
              loading={withdraw.isPending}
              disabled={locked || withdraw.isError || completed}
            >
              {applicationPage.withdraw.confirm}
            </Button>
          </Group>
        </Stack>
      </Modal>
    </>
  );
}
