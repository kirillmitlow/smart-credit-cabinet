import { useState } from 'react';
import {
  Alert,
  Anchor,
  Button,
  Grid,
  Group,
  Paper,
  Skeleton,
  Stack,
  Text,
  Title,
} from '@mantine/core';
import { Link, useParams, useSearchParams } from 'react-router';
import { isAppError } from '@/api/errors';
import { useGetBackofficeApplication } from '@/api/generated/api';
import { tokens } from '@/app/theme';
import { PageHero } from '@/components/PageHero';
import { ProblemAlert } from '@/components/ProblemAlert';
import { formatDate, formatMoney, formatTermMonths } from '@/lib/format';
import { usePageHeading } from '@/lib/usePageHeading';
import { applicationStatusLabels, fill, productName } from '@/texts';
import { bankCard as t, bankWorkspace } from '@/texts/bank';
import { BankAssessmentPanels } from './BankAssessmentPanels';
import { BankEvidencePanels } from './BankEvidencePanels';
import { bankLabel } from './bankFormatting';
import { BankRecommendationView } from './BankRecommendationView';
import { BankOutboxPanel } from './BankOutboxPanel';
import { BankActions } from './BankActions';
import { BankClientRequests } from './BankClientRequests';

export function BankApplicationPage() {
  const { id = '' } = useParams();
  const [search] = useSearchParams();
  const value = Number(search.get('expectedVersion'));
  return (
    <BankApplication
      key={id}
      id={id}
      expected={Number.isInteger(value) && value > 0 ? value : undefined}
    />
  );
}

function BankApplication({ id, expected }: { id: string; expected: number | undefined }) {
  const [baseline, setBaseline] = useState(expected);
  const [search, setSearch] = useSearchParams();
  const query = useGetBackofficeApplication(id, { expectedVersion: baseline });
  const card = query.data?.status === 200 ? query.data.data : undefined;
  const heading = usePageHeading(card ? fill(t.title, { number: card.number }) : t.titleLoading);
  if (baseline === undefined && card) setBaseline(card.version);
  const refresh = () => {
    if (card && baseline !== card.version) {
      setBaseline(card.version);
      const params = new URLSearchParams(search);
      params.set('expectedVersion', String(card.version));
      void setSearch(params, { replace: true });
    } else void query.refetch();
  };
  const decision = card?.decision ?? null;
  const incomplete =
    card?.sourceSnapshots.some(
      (source) => source.usedByCurrentDecision && source.status === 'UNAVAILABLE',
    ) ?? false;
  const age = decision?.features?.business_age_months;
  return (
    <Stack gap="md">
      <PageHero>
        <Stack gap="md">
          <Anchor
            component={Link}
            to="/bank"
            fw={600}
            underline="never"
            style={{ color: tokens.header.color, alignSelf: 'flex-start' }}
          >
            <span aria-hidden="true">← </span>
            {t.back}
          </Anchor>
          <Group justify="space-between" align="flex-end">
            <Stack gap={6}>
              <Title order={1} ref={heading} tabIndex={-1} c="inherit">
                {card ? fill(t.title, { number: card.number }) : t.titleLoading}
              </Title>
            </Stack>
            <Button
              variant="outline"
              color="gray"
              loading={query.isFetching}
              onClick={refresh}
              styles={{
                root: { color: tokens.header.color, borderColor: tokens.header.border },
              }}
            >
              {t.refresh}
            </Button>
          </Group>
        </Stack>
      </PageHero>
      {query.isPending ? (
        <Stack role="status" aria-label={t.loading}>
          <Skeleton height={150} />
          <Text>{t.loading}</Text>
        </Stack>
      ) : null}
      {query.isError ? (
        isAppError(query.error) && query.error.status === 404 ? (
          <Alert color="red">{t.notFound}</Alert>
        ) : (
          <ProblemAlert error={query.error} onAction={() => void query.refetch()} />
        )
      ) : null}
      {card ? (
        <>
          {card.stale ? (
            <Alert color="yellow" role="status" data-testid="bank-card-stale">
              {t.changed}
            </Alert>
          ) : null}
          <BankActions card={card} />
          <Paper withBorder p="md" data-testid="bank-request">
            <Title order={2} size="h3">
              {t.request}
            </Title>
            <Grid mt="sm">
              <Grid.Col span={{ base: 12, md: 6 }}>
                <Text fw={600}>{card.company.name}</Text>
                <Text size="sm">{fill(bankWorkspace.inn, { inn: card.company.inn })}</Text>
                <Text size="sm">
                  {card.company.isBankCustomer === null
                    ? bankWorkspace.unknownClient
                    : card.company.isBankCustomer
                      ? bankWorkspace.client
                      : bankWorkspace.notClient}
                </Text>
                <Text size="sm">
                  {t.registered}: {formatDate(card.company.registeredOn)}
                </Text>
                <Text size="sm">
                  {t.age}: {typeof age === 'number' ? formatTermMonths(age) : t.noData}
                </Text>
                <Text size="sm">
                  {t.okved}: {card.company.okved ?? t.noData}
                </Text>
              </Grid.Col>
              <Grid.Col span={{ base: 12, md: 6 }}>
                <Text fw={600}>{productName(card.productCode)}</Text>
                <Text>
                  {formatMoney(card.amountRub)} · {formatTermMonths(card.termMonths)}
                </Text>
                <Text size="sm">
                  {t.submittedBy}: {card.submittedBy.name}
                  {card.submittedBy.companyRole
                    ? ` · ${bankLabel(t.role, card.submittedBy.companyRole)}`
                    : ''}
                </Text>
                <Text size="sm">
                  {t.status}: {bankLabel(applicationStatusLabels, card.status)}
                </Text>
                <Text size="xs">
                  {t.version}: {card.version}
                </Text>
              </Grid.Col>
            </Grid>
          </Paper>
          <Paper withBorder p="md" data-testid="bank-recommendation">
            <Title order={2} size="h3">
              {t.recommendation}
            </Title>
            <Stack gap="xs" mt="sm">
              <BankRecommendationView value={card.engineRecommendation} />
              {decision ? (
                <>
                  <Text size="sm">
                    {t.level}: {decision.requiredLevel}
                  </Text>
                  <Text size="xs">
                    {t.policy}: {decision.policy.version} · {t.engine}: {decision.engineVersion}
                  </Text>
                  <details>
                    <summary>{t.original}</summary>
                    <Text size="xs" style={{ overflowWrap: 'anywhere' }}>
                      {t.policyHash}: {decision.policy.contentHash}
                    </Text>
                    <Text size="xs" style={{ overflowWrap: 'anywhere' }}>
                      {t.inputsHash}: {decision.inputsHash}
                    </Text>
                  </details>
                </>
              ) : null}
            </Stack>
          </Paper>
          <BankAssessmentPanels decision={decision} incomplete={incomplete} />
          <BankEvidencePanels card={card} />
          <BankClientRequests card={card} />
          <BankOutboxPanel applicationId={card.id} />
        </>
      ) : null}
    </Stack>
  );
}
