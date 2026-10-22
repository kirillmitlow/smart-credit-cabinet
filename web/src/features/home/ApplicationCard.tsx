import { Badge, Button, Card, Group, Stack, Text, VisuallyHidden } from '@mantine/core';
import { Link } from 'react-router';
import type { ApplicationOut } from '@/api/generated/model';
import { statusLabel } from '@/features/application/statuses';
import { formatMoney, formatTermMonths } from '@/lib/format';
import { fill, home, productName } from '@/texts';

/** Карточка заявки на главной: номер, условия, статус одним шагом и «Открыть» (позже — общий компонент T-413) */
export function ApplicationCard({ application }: { application: ApplicationOut }) {
  const label = statusLabel(application.status);
  const product = productName(application.productCode);
  const isDraft = application.status === 'DRAFT';
  const conditions =
    application.amountRub !== null && application.termMonths !== null
      ? fill(home.applications.summary, {
          amount: formatMoney(application.amountRub),
          term: formatTermMonths(application.termMonths),
        })
      : home.applications.noConditions;
  const to = isDraft ? `/applications/${application.id}/edit/1` : `/applications/${application.id}`;
  const heading = fill(home.applications.numberLabel, { number: application.number });

  return (
    <Card withBorder padding="md" data-testid="application-card">
      <Group justify="space-between" wrap="nowrap" align="center">
        <Stack gap={2}>
          <Text fw={600}>{heading}</Text>
          <Text>{product ?? home.applications.noProduct}</Text>
          <Text size="sm" c="dimmed">
            {conditions}
          </Text>
        </Stack>
        <Group gap="md" wrap="nowrap">
          {label ? (
            <Badge variant="light" size="lg" data-testid="application-status">
              {label}
            </Badge>
          ) : null}
          <Button component={Link} to={to} variant={isDraft ? 'filled' : 'light'}>
            {isDraft ? home.applications.resume : home.applications.open}
            <VisuallyHidden>{` ${heading}`}</VisuallyHidden>
          </Button>
        </Group>
      </Group>
    </Card>
  );
}
