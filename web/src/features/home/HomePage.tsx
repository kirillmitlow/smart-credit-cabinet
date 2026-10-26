import {
  Alert,
  Box,
  Button,
  Group,
  Paper,
  SimpleGrid,
  Skeleton,
  Stack,
  Text,
  Title,
} from '@mantine/core';
import { useInfiniteQuery, useQueries, useQueryClient } from '@tanstack/react-query';
import { Link, useNavigate } from 'react-router';
import {
  getListApplicationTasksQueryOptions,
  useCreateApplication,
  getListApplicationsQueryKey,
  listApplications,
} from '@/api/generated/api';
import type { ApplicationOut, TaskList } from '@/api/generated/model';
import { useActionKey } from '@/api/idempotency';
import { tokens } from '@/app/theme';
import { PageHero } from '@/components/PageHero';
import { ProblemAlert } from '@/components/ProblemAlert';
import { SectionCard } from '@/components/SectionCard';
import { isInFlight } from '@/features/application/statuses';
import { companyStatusText } from '@/features/auth/labels';
import { useActiveCompany } from '@/features/auth/useActiveCompany';
import { usePageHeading } from '@/lib/usePageHeading';
import { emptyStates, fill, home } from '@/texts';
import { putApplication } from '@/features/application/useApplication';
import { unwrapTasks } from '@/features/application/useTasks';
import { HomeLoans } from '@/features/loans/HomeLoans';
import { ApplicationCard } from './ApplicationCard';
import { tasksFrom } from './tasks';

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
  const applications = useInfiniteQuery({
    queryKey: [...getListApplicationsQueryKey({ limit: 20 }), 'pages', choice?.company.id],
    initialPageParam: null as string | null,
    queryFn: async ({ pageParam, signal }) => {
      const response = await listApplications(
        { limit: 20, ...(pageParam ? { cursor: pageParam } : {}) },
        { signal },
      );
      if (response.status !== 200) throw new Error('Unexpected application list response');
      return response.data;
    },
    getNextPageParam: (page) => page.nextCursor ?? undefined,
  });
  const action = useActionKey();
  const create = useCreateApplication({ request: action.request() });

  const items: ApplicationOut[] = applications.data
    ? [
        ...new Map(
          applications.data.pages.flatMap((page) => page.items).map((item) => [item.id, item]),
        ).values(),
      ]
    : [];
  const more = () => void applications.fetchNextPage({ cancelRefetch: false });
  const retryApplications = () => {
    if (applications.isFetchNextPageError) more();
    else void applications.refetch();
  };
  const hasDraft = items.some((item) => item.status === 'DRAFT');
  // Запросы банка по заявкам, где ждут ответа клиента: по ним строки «Что нужно от вас»
  const respondIds = items
    .filter((item) => item.allowedActions.includes('RESPOND'))
    .map((item) => item.id);
  const taskLists = useQueries({
    queries: respondIds.map((id) => ({
      ...getListApplicationTasksQueryOptions(id, { query: { select: unwrapTasks } }),
    })),
  });
  const tasksByApplication = new Map<string, TaskList>();
  respondIds.forEach((id, index) => {
    const loaded = taskLists[index]?.data;
    if (loaded) tasksByApplication.set(id, loaded);
  });
  const tasks = tasksFrom(items, tasksByApplication);
  const taskLoadFailed = applications.isError || taskLists.some((query) => query.isError);
  const retryTasks = () => {
    if (applications.isError) retryApplications();
    for (const query of taskLists) if (query.isError) void query.refetch();
  };
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

  const tasksBody = applications.isPending ? (
    <Skeleton height={40} radius="md" />
  ) : tasks.length === 0 && !taskLoadFailed ? (
    <Text>{emptyStates.tasks}</Text>
  ) : (
    <Stack component="ul" gap="sm" p={0} m={0} style={{ listStyle: 'none' }}>
      {tasks.map((task) => (
        <li key={task.key}>
          <Group justify="space-between" wrap="nowrap" gap="lg">
            <Text fw={600} fz={18} c="inherit">
              {task.label}
            </Text>
            <Button component={Link} to={task.to} variant="white" color="dark" size="md">
              {home.tasks.open}
            </Button>
          </Group>
        </li>
      ))}
    </Stack>
  );
  const hasTasks = tasks.length > 0;

  return (
    <Stack gap="lg">
      <PageHero>
        <Group justify="space-between" align="flex-end" gap="lg">
          <Stack gap={8}>
            <Title order={1} ref={headingRef} tabIndex={-1} c="inherit">
              {home.title}
            </Title>
            {hasTasks ? (
              <Text fz={18} style={{ color: tokens.header.muted }}>
                {fill(home.waiting, { count: tasks.length })}
              </Text>
            ) : null}
          </Stack>
          <Stack gap={6} align="flex-end">
            {canApply ? (
              <Button component={Link} to="/wizard" size="lg" variant="white" color="dark">
                {home.needMoney}
              </Button>
            ) : (
              <Button size="lg" disabled>
                {home.needMoney}
              </Button>
            )}
            <Text size="sm" style={{ color: tokens.header.muted }}>
              {home.needMoneyHint}
            </Text>
          </Stack>
        </Group>
      </PageHero>

      {canApply ? null : (
        <Alert color="yellow" role="status">
          {fill(home.notActive, { status: statusText })}
        </Alert>
      )}

      <Paper
        component="section"
        aria-labelledby="home-tasks"
        p={28}
        bg={hasTasks ? 'brand.6' : undefined}
        c={hasTasks ? 'white' : undefined}
        data-testid="home-tasks"
      >
        <Stack gap="md">
          <Group gap="sm" align="baseline">
            {hasTasks ? (
              <Text fz={13} fw={700} tt="uppercase" style={{ letterSpacing: '0.08em' }} c="inherit">
                {home.tasks.now}
              </Text>
            ) : null}
            <Title order={2} size={hasTasks ? 'h2' : 'h3'} id="home-tasks" c="inherit">
              {home.tasks.heading}
            </Title>
          </Group>
          {tasksBody}
          {taskLoadFailed ? (
            <Alert color="yellow" role="status">
              <Stack gap="xs" align="flex-start">
                <Text>{home.tasks.loadFailed}</Text>
                <Button variant="light" size="compact-sm" onClick={retryTasks}>
                  {home.tasks.retry}
                </Button>
              </Stack>
            </Alert>
          ) : null}
        </Stack>
      </Paper>

      <SimpleGrid cols={{ base: 1, md: 3 }} spacing="lg">
        <Box style={{ gridColumn: 'span 2' }}>
          <SectionCard id="home-applications" title={home.applications.heading}>
            {applications.isPending ? (
              <ListSkeleton />
            ) : applications.isError && items.length === 0 ? (
              <ProblemAlert error={applications.error} onAction={retryApplications} />
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
            {items.length > 0 && applications.error ? (
              <ProblemAlert error={applications.error} onAction={retryApplications} />
            ) : null}
            {applications.hasNextPage ? (
              <Text size="sm" c="dimmed" role="status">
                {fill(home.applications.moreShown, { count: items.length })}
              </Text>
            ) : null}
            {applications.hasNextPage ? (
              <Button
                variant="default"
                loading={applications.isFetchingNextPage}
                disabled={applications.isFetching}
                onClick={more}
                w="fit-content"
              >
                {home.applications.loadMore}
              </Button>
            ) : null}
            {canApply &&
            !hasDraft &&
            inProgressCount === 0 &&
            !applications.isPending &&
            !applications.isError &&
            !applications.hasNextPage ? (
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
          </SectionCard>
        </Box>
        <SectionCard id="home-loans" title={home.loans.heading}>
          <HomeLoans />
        </SectionCard>
      </SimpleGrid>
    </Stack>
  );
}
