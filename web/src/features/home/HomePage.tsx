import type { ReactNode } from 'react';
import { Alert, Button, Group, Skeleton, Stack, Text, Title } from '@mantine/core';
import { useQueryClient } from '@tanstack/react-query';
import { Link, useNavigate } from 'react-router';
import { useCreateApplication, useListApplications } from '@/api/generated/api';
import type { ApplicationOut } from '@/api/generated/model';
import { useActionKey } from '@/api/idempotency';
import { ProblemAlert } from '@/components/ProblemAlert';
import { isInFlight } from '@/features/application/statuses';
import { companyStatusText } from '@/features/auth/labels';
import { useActiveCompany } from '@/features/auth/useActiveCompany';
import { usePageHeading } from '@/lib/usePageHeading';
import { emptyStates, fill, home } from '@/texts';
import { putApplication } from '@/features/application/useApplication';
import { ApplicationCard } from './ApplicationCard';
import { tasksFrom } from './tasks';

function Section({ id, title, children }: { id: string; title: string; children: ReactNode }) {
  return (
    <Stack component="section" gap="sm" aria-labelledby={id}>
      <Title order={2} size="h3" id={id}>
        {title}
      </Title>
      {children}
    </Stack>
  );
}

function ListSkeleton() {
  return (
    <Stack gap="sm" role="status" aria-label={home.applications.loading}>
      <Skeleton height={72} radius="md" />
      <Skeleton height={72} radius="md" />
    </Stack>
  );
}

/** Главная клиента (60-03 №3): задачи, заявки, кредиты и крупная кнопка «Нужны деньги» */
export function HomePage() {
  const headingRef = usePageHeading(home.title);
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const { canApply, choice } = useActiveCompany();
  const applications = useListApplications({ limit: 20 });
  const action = useActionKey();
  const create = useCreateApplication({ request: action.request() });

  const items: ApplicationOut[] =
    applications.data?.status === 200 ? applications.data.data.items : [];
  const hasDraft = items.some((item) => item.status === 'DRAFT');
  const tasks = tasksFrom(items);
  const inProgressCount = items.filter((item) => isInFlight(item.status)).length;
  const statusText = companyStatusText(choice?.company.status);

  const startDirect = () => {
    create.mutate(
      { data: {} },
      {
        onSuccess: (response) => {
          action.reset();
          if (response.status !== 201) return;
          const created = response.data;
          putApplication(queryClient, created);
          void queryClient.invalidateQueries({ queryKey: ['/applications'] });
          void navigate(`/applications/${created.id}/edit/1`);
        },
      },
    );
  };

  return (
    <Stack gap="xl">
      <Group justify="space-between" align="flex-start">
        <Title order={1} ref={headingRef} tabIndex={-1}>
          {home.title}
        </Title>
        <Stack gap={4} align="flex-end">
          {canApply ? (
            <Button component={Link} to="/wizard" size="lg">
              {home.needMoney}
            </Button>
          ) : (
            <Button size="lg" disabled>
              {home.needMoney}
            </Button>
          )}
          <Text size="sm" c="dimmed">
            {home.needMoneyHint}
          </Text>
        </Stack>
      </Group>

      {canApply ? null : (
        <Alert color="yellow" role="status">
          {fill(home.notActive, { status: statusText })}
        </Alert>
      )}

      <Section id="home-tasks" title={home.tasks.heading}>
        {applications.isPending ? (
          <Skeleton height={40} radius="md" />
        ) : tasks.length === 0 ? (
          <Text>{emptyStates.tasks}</Text>
        ) : (
          <Stack component="ul" gap="xs" p={0} m={0} style={{ listStyle: 'none' }}>
            {tasks.map((task) => (
              <li key={task.key}>
                <Group justify="space-between" wrap="nowrap">
                  <Text fw={600}>{task.label}</Text>
                  <Button component={Link} to={task.to} variant="light" size="compact-md">
                    {home.tasks.open}
                  </Button>
                </Group>
              </li>
            ))}
          </Stack>
        )}
      </Section>

      <Section id="home-applications" title={home.applications.heading}>
        {applications.isPending ? (
          <ListSkeleton />
        ) : applications.isError ? (
          <ProblemAlert
            error={applications.error}
            onAction={() => {
              void applications.refetch();
            }}
          />
        ) : items.length === 0 ? (
          <Stack gap="sm" align="flex-start" data-testid="applications-empty">
            <Text>{emptyStates.homeNoApplications.text}</Text>
            <Group>
              {canApply ? (
                <Button component={Link} to="/wizard">
                  {emptyStates.homeNoApplications.action}
                </Button>
              ) : null}
            </Group>
          </Stack>
        ) : (
          <Stack component="ul" gap="sm" p={0} m={0} style={{ listStyle: 'none' }}>
            {items.map((item) => (
              <li key={item.id}>
                <ApplicationCard application={item} />
              </li>
            ))}
          </Stack>
        )}
        {canApply && !hasDraft && inProgressCount === 0 && !applications.isPending ? (
          <Group gap="sm" align="baseline">
            <Button variant="subtle" px={0} onClick={startDirect} loading={create.isPending}>
              {home.startDirect}
            </Button>
            <Text size="sm" c="dimmed">
              {home.startDirectHint}
            </Text>
          </Group>
        ) : null}
        {create.isError ? <ProblemAlert error={create.error} /> : null}
      </Section>

      <Section id="home-loans" title={home.loans.heading}>
        <Text>{emptyStates.loans}</Text>
      </Section>
    </Stack>
  );
}
