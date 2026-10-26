import { Badge, Button, Group, Paper, Stack, Text, VisuallyHidden } from '@mantine/core';
import { Link } from 'react-router';
import { tokens } from '@/app/theme';
import type { ApplicationOut } from '@/api/generated/model';
import { statusLabel } from '@/features/application/statuses';
import { formatMoney, formatTermMonths } from '@/lib/format';
import { fill, home, productName } from '@/texts';

/** Ждёт ли заявка действия клиента: такой статус подсвечиваем тёплым цветом */
const CLIENT_ACTIONS = new Set(['ACCEPT_OFFER', 'RESPOND', 'SIGN', 'EDIT_DRAFT']);

function badgeStyle(application: ApplicationOut) {
  if (application.allowedActions.some((action) => CLIENT_ACTIONS.has(action))) {
    return tokens.status.waiting;
  }
  if (application.status === 'DISBURSED' || application.status === 'APPROVED') {
    return tokens.status.success;
  }
  return { background: '#eeeef0', color: '#17171a' };
}

/** Карточка заявки на главной: номер, продукт, сумма крупно, статус и «Открыть» (D-113) */
export function ApplicationCard({ application }: { application: ApplicationOut }) {
  const label = statusLabel(application.status);
  const product = productName(application.productCode);
  const isDraft = application.status === 'DRAFT';
  const hasConditions = application.amountRub !== null && application.termMonths !== null;
  const conditions = hasConditions
    ? fill(home.applications.summary, {
        amount: formatMoney(application.amountRub),
        term: formatTermMonths(application.termMonths),
      })
    : home.applications.noConditions;
  const to = isDraft ? `/applications/${application.id}/edit/1` : `/applications/${application.id}`;
  const heading = fill(home.applications.numberLabel, { number: application.number });
  const badge = badgeStyle(application);

  return (
    <Paper withBorder radius="md" p="lg" data-testid="application-card">
      <Group justify="space-between" wrap="nowrap" align="center" gap="lg">
        <Stack gap={4} miw={0}>
          <Group gap="sm" wrap="wrap">
            <Text size="sm" c="dimmed">
              {heading}
            </Text>
            {label ? (
              <Badge
                size="lg"
                radius="xl"
                tt="none"
                data-testid="application-status"
                styles={{ root: { background: badge.background, color: badge.color } }}
              >
                {label}
              </Badge>
            ) : null}
          </Group>
          <Text fw={700} fz={18}>
            {product ?? home.applications.noProduct}
          </Text>
          <Text c={hasConditions ? undefined : 'dimmed'} className="scc-num">
            {conditions}
          </Text>
        </Stack>
        <Button
          component={Link}
          to={to}
          variant={isDraft ? 'filled' : 'outline'}
          color={isDraft ? undefined : 'dark'}
        >
          {isDraft ? home.applications.resume : home.applications.open}
          <VisuallyHidden>{` ${heading}`}</VisuallyHidden>
        </Button>
      </Group>
    </Paper>
  );
}
