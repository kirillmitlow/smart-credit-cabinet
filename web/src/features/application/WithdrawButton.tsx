import { Button, Group, Modal, Stack, Text } from '@mantine/core';
import { useDisclosure } from '@mantine/hooks';
import { useQueryClient } from '@tanstack/react-query';
import { useWithdrawApplication } from '@/api/generated/api';
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

  const confirm = () => {
    withdraw.mutate(
      { applicationId: application.id },
      {
        onSuccess: (response) => {
          action.reset();
          if (response.status === 200) putApplication(queryClient, response.data);
          void queryClient.invalidateQueries({ queryKey: ['/applications'] });
          close();
        },
      },
    );
  };

  return (
    <>
      <Button variant="subtle" color="gray" onClick={open}>
        {asDecline ? applicationPage.withdraw.decline : applicationPage.withdraw.action}
      </Button>
      <Modal
        opened={opened}
        onClose={close}
        title={applicationPage.withdraw.title}
        closeOnClickOutside={!withdraw.isPending}
      >
        <Stack>
          <Text>{applicationPage.withdraw.body}</Text>
          {withdraw.isError ? <ProblemAlert error={withdraw.error} /> : null}
          <Group justify="flex-end">
            <Button variant="default" onClick={close} disabled={withdraw.isPending}>
              {applicationPage.withdraw.cancel}
            </Button>
            <Button onClick={confirm} loading={withdraw.isPending}>
              {applicationPage.withdraw.confirm}
            </Button>
          </Group>
        </Stack>
      </Modal>
    </>
  );
}
