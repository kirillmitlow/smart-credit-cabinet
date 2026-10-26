import { useState } from 'react';
import {
  Alert,
  Button,
  Badge,
  Paper,
  Group,
  List,
  Loader,
  SimpleGrid,
  Stack,
  Text,
  Title,
} from '@mantine/core';
import { useGetApplicationDecision } from '@/api/generated/api';
import type { ApplicationOut, ClientDecisionOut, VariantOut } from '@/api/generated/model';
import { PaymentKind } from '@/api/generated/model';
import { tokens } from '@/app/theme';
import { ProblemAlert } from '@/components/ProblemAlert';
import { VariantCard } from '@/components/VariantCard';
import { OfferActions } from '@/features/offers/OfferActions';
import { formatDateTime, formatMoney, formatTermMonths } from '@/lib/format';
import { counterOffer as t, decision, fill, outcomes } from '@/texts';
import {
  isInterestOnly,
  needsSecurityFallback,
  uniqueLines,
  variantChanges,
  variantRequirements,
} from './counterOfferModel';
import { SchedulePreview } from './SchedulePreview';

function CardDetails({ variant }: { variant: VariantOut }) {
  const changes = variantChanges(variant);
  const requirements = variantRequirements(variant);
  const securityFallback = needsSecurityFallback(variant);
  return (
    <Stack gap="md">
      {changes.length > 0 ? (
        <Stack gap={4}>
          <Text fw={600}>{t.changedHeading}</Text>
          <List size="sm" spacing={2}>
            {changes.map((change) => (
              <List.Item key={change.field}>
                {fill(t.changeLine, {
                  what: t.changed[change.field],
                  from: change.from,
                  to: change.to,
                })}
              </List.Item>
            ))}
          </List>
        </Stack>
      ) : null}
      <Stack gap={4}>
        <Text fw={600}>{t.needsHeading}</Text>
        {requirements.length > 0 || securityFallback ? (
          <List size="sm" spacing={2}>
            {requirements.map((line) => (
              <List.Item key={line}>{line}</List.Item>
            ))}
            {securityFallback ? <List.Item>{t.needsSecurity}</List.Item> : null}
          </List>
        ) : (
          <Text size="sm">{t.needsNothing}</Text>
        )}
      </Stack>
      <SchedulePreview terms={variant} />
    </Stack>
  );
}

function HowToGetRequested({
  application,
  data,
}: {
  application: ApplicationOut;
  data: ClientDecisionOut;
}) {
  const blocking = uniqueLines(
    data.whatAffected.length ? data.whatAffected : data.reasons.map((reason) => reason.text),
  );
  const steps = uniqueLines(
    data.nextSteps.length ? data.nextSteps : data.reasons.map((reason) => reason.action),
  );
  // Рычагов «что изменить, чтобы одобрили исходный запрос» в API пока нет (T-299): без причин блок пуст
  if (!blocking.length && !steps.length) return null;
  return (
    <Paper p={28} component="section" aria-labelledby="how-to-title" data-testid="how-to-block">
      <Stack gap="sm">
        <Title order={3} id="how-to-title">
          {t.how.heading}
        </Title>
        {application.amountRub !== null && application.termMonths !== null ? (
          <Text>
            {fill(t.how.requested, {
              amount: formatMoney(application.amountRub),
              term: formatTermMonths(application.termMonths),
            })}
          </Text>
        ) : null}
        {blocking.length > 0 ? (
          <Stack gap={4}>
            <Text fw={600}>{t.how.blocking}</Text>
            <List>
              {blocking.map((line) => (
                <List.Item key={line}>{line}</List.Item>
              ))}
            </List>
          </Stack>
        ) : null}
        {steps.length > 0 ? (
          <Stack gap={4}>
            <Text fw={600}>{t.how.steps}</Text>
            <List>
              {steps.map((line) => (
                <List.Item key={line}>{line}</List.Item>
              ))}
            </List>
          </Stack>
        ) : null}
      </Stack>
    </Paper>
  );
}

/**
 * Встречное предложение (60-03 №10): до трёх карточек, «рекомендуем» и сами числа даёт сервер.
 * Выбор карточки — то же принятие, что у одобрения (`OfferActions`): после него статус заявки
 * меняется и страница показывает подпись договора.
 */
export function CounterOfferPanel({ application }: { application: ApplicationOut }) {
  const query = useGetApplicationDecision(application.id, {
    query: { select: (response) => (response.status === 200 ? response.data : undefined) },
  });
  const [pendingId, setPendingId] = useState<string | null>(null);
  const data = query.data;
  const offer = data?.outcome === 'COUNTER_OFFER' ? data.offer : null;
  const ready = offer !== null && offer.variantsStatus === 'READY' && offer.variants.length > 0;
  const canAccept = !query.isError && application.allowedActions.includes('ACCEPT_OFFER');

  return (
    <Stack component="section" aria-labelledby="outcome-title" gap="lg">
      <Stack gap="xs">
        <Title order={2} id="outcome-title">
          {outcomes.counter.title}
        </Title>
        <Text fz={17}>{t.lead}</Text>
      </Stack>

      {query.isPending ? (
        <Group role="status">
          <Loader size="sm" />
          <Text>{decision.loading}</Text>
        </Group>
      ) : null}
      {query.isError ? (
        <ProblemAlert
          error={query.error}
          onAction={() => {
            void query.refetch();
          }}
        />
      ) : null}
      {data && !offer ? <Alert color="yellow">{t.noOffer}</Alert> : null}
      {offer && !ready ? <Alert color="yellow">{t.pending}</Alert> : null}

      {offer && ready ? (
        <Stack gap="md">
          <Badge
            size="lg"
            radius="xl"
            tt="none"
            styles={{ root: { ...tokens.status.waiting, alignSelf: 'flex-start' } }}
          >
            {fill(t.expires, { date: formatDateTime(offer.expiresAt) })}
          </Badge>
          <SimpleGrid
            cols={{ base: 1, md: Math.min(offer.variants.length, 3) }}
            spacing="md"
            role="group"
            aria-label={t.cardsLabel}
          >
            {offer.variants.slice(0, 3).map((variant) => (
              <VariantCard
                key={variant.id}
                id={`variant-${variant.id}`}
                title={variant.label}
                recommended={variant.recommended}
                why={variant.note}
                amountRub={variant.amountRub}
                termMonths={variant.termMonths}
                paymentRub={variant.paymentRub}
                paymentKind={isInterestOnly(variant) ? PaymentKind.INTEREST_ONLY : null}
                overpaymentRub={variant.overpaymentRub}
                ratePercentFrom={variant.ratePercent}
                rateExact
                note={<CardDetails variant={variant} />}
                actions={
                  canAccept ? (
                    <OfferActions
                      offer={offer}
                      variantId={variant.id}
                      label={t.choose}
                      describedBy={`variant-${variant.id}-title`}
                      secondary={!variant.recommended}
                      fullWidth
                      disabled={pendingId !== null && pendingId !== variant.id}
                      onPendingChange={(pending) => {
                        setPendingId((current) =>
                          pending ? variant.id : current === variant.id ? null : current,
                        );
                      }}
                    />
                  ) : null
                }
              />
            ))}
          </SimpleGrid>
        </Stack>
      ) : null}

      {data ? <HowToGetRequested application={application} data={data} /> : null}

      {!query.isPending && !query.isError && (!data || !offer || !ready) ? (
        <div>
          <Button
            variant="light"
            onClick={() => {
              void query.refetch();
            }}
          >
            {decision.refresh}
          </Button>
        </div>
      ) : null}
    </Stack>
  );
}
