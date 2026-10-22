import { Badge, Button, Card, Group, Stack, Text, Title } from '@mantine/core';
import { useQueryClient } from '@tanstack/react-query';
import { Link, useNavigate, useSearchParams } from 'react-router';
import { useSetActiveCompany } from '@/api/generated/api';
import { sessionQueryKey } from '@/api/session-keys';
import { ProblemAlert } from '@/components/ProblemAlert';
import { usePageHeading } from '@/lib/usePageHeading';
import { companyChoice, fill, shell } from '@/texts';
import { companyStatusText, roleText } from './labels';
import { safeNext } from './loginUrl';
import { useSession } from './session';

/**
 * «Выбор компании» (60-03 №2): от чьего имени работаем. Сюда ведёт вход, если активной компании нет,
 * и ссылка «Сменить компанию» в шапке.
 */
export function CompanyPage() {
  const headingRef = usePageHeading(companyChoice.title);
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const [params] = useSearchParams();
  const next = safeNext(params.get('next')) ?? '/';
  const me = useSession('client').data;
  const choose = useSetActiveCompany();
  const companies = me?.companies ?? [];

  const select = (companyId: string) => {
    choose.mutate(
      { data: { companyId } },
      {
        onSuccess: (response) => {
          if (response.status !== 200) return;
          // заявки и задачи прошлой компании в кэше больше не нужны
          queryClient.removeQueries({
            predicate: (query) =>
              query.queryKey[0] !== 'session' && query.queryKey[0] !== 'public-config',
          });
          queryClient.setQueryData(sessionQueryKey('client'), response.data);
          void navigate(next, { replace: true });
        },
      },
    );
  };

  return (
    <Stack gap="lg" maw={640}>
      <Stack gap={4}>
        <Title order={1} ref={headingRef} tabIndex={-1}>
          {companyChoice.title}
        </Title>
        <Text c="dimmed">{companyChoice.body}</Text>
      </Stack>

      {companies.length === 0 ? <Text>{companyChoice.empty}</Text> : null}

      <Stack component="ul" gap="sm" p={0} m={0} style={{ listStyle: 'none' }}>
        {companies.map((item) => {
          const active = item.company.id === me?.activeCompanyId;
          return (
            <li key={item.company.id}>
              <Card withBorder padding="md" data-testid="company-option">
                <Group justify="space-between" wrap="nowrap" align="center">
                  <Stack gap={2}>
                    <Text fw={600}>{item.company.name}</Text>
                    <Text size="sm" c="dimmed">
                      {fill(companyChoice.innLine, { inn: item.company.inn })}
                      {', '}
                      {roleText(item.role)}
                      {', '}
                      {companyStatusText(item.company.status)}
                    </Text>
                    {item.company.canApply ? null : (
                      <Badge variant="light" color="yellow">
                        {companyChoice.notActive}
                      </Badge>
                    )}
                  </Stack>
                  <Button
                    variant={active ? 'default' : 'filled'}
                    disabled={active || choose.isPending}
                    onClick={() => select(item.company.id)}
                  >
                    {active ? companyChoice.current : companyChoice.select}
                  </Button>
                </Group>
              </Card>
            </li>
          );
        })}
      </Stack>

      {choose.isError ? <ProblemAlert error={choose.error} /> : null}

      {me?.activeCompanyId ? (
        <Group>
          <Button component={Link} to={next} variant="subtle">
            {shell.common.back}
          </Button>
        </Group>
      ) : null}
    </Stack>
  );
}
