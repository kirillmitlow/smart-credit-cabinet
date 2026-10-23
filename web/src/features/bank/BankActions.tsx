import { useRef, useState } from 'react';
import {
  Alert,
  Button,
  Group,
  Modal,
  NativeSelect,
  Paper,
  Stack,
  Text,
  Textarea,
  TextInput,
  Title,
} from '@mantine/core';
import { useMutation, useQueryClient } from '@tanstack/react-query';
import { useNavigate } from 'react-router';
import { isAppError } from '@/api/errors';
import {
  requestBackofficeInformation,
  recheckBackofficeApplication,
  saveBackofficeDecision,
} from '@/api/generated/api';
import type {
  BankApplicationCard,
  BankDecisionRequest,
  BankInfoItem,
  BankInfoRequestReasonCode,
} from '@/api/generated/model';
import { useActionKey } from '@/api/idempotency';
import { ProblemAlert } from '@/components/ProblemAlert';
import { useSession } from '@/features/auth/session';
import { formatMoney, formatTermMonths } from '@/lib/format';
import { fill, productName } from '@/texts';
import { bankActions as t } from '@/texts/bankActions';

type Action = 'APPROVED' | 'REJECTED' | 'COUNTER_OFFER' | 'INFO' | 'RECHECK';
const labels: Record<Action, string> = {
  APPROVED: t.approve,
  REJECTED: t.reject,
  COUNTER_OFFER: t.counter,
  INFO: t.info,
  RECHECK: t.recheck,
};
const reasons = [
  { value: '', label: t.chooseReason },
  ...Object.entries(t.reasonOptions).map(([value, label]) => ({ value, label })),
];

export function BankActions({ card }: { card: BankApplicationCard }) {
  const [opened, setOpened] = useState<{ action: Action; card: BankApplicationCard } | null>(null);
  const session = useSession('bank');
  const level = session.data?.level;
  const lower = level === 'L1' && card.decision?.requiredLevel === 'L2';
  const manual = card.status === 'MANUAL_REVIEW';
  const engineReady = card.decision?.outcome === 'MANUAL_REVIEW' && Boolean(card.engineDecisionId);
  if (!manual && !opened) return null;
  return (
    <Paper withBorder p="md" id="bank-actions" data-testid="bank-actions">
      <Stack gap="sm">
        <Title order={2} size="h3">
          {t.title}
        </Title>
        <Text size="sm">
          {fill(t.requiredLevel, { level: card.decision?.requiredLevel ?? '—' })} ·{' '}
          {fill(t.yourLevel, { level: level ?? '—' })}
        </Text>
        {lower ? <Alert color="yellow">{t.lowerLevel}</Alert> : null}
        {!engineReady ? <Text size="sm">{t.noDecision}</Text> : null}
        <Group>
          {(Object.keys(labels) as Action[]).map((action) => (
            <Button
              key={action}
              variant={action === 'APPROVED' ? 'filled' : 'light'}
              color={action === 'REJECTED' ? 'red' : undefined}
              disabled={
                card.stale ||
                !manual ||
                !level ||
                (action !== 'INFO' && action !== 'RECHECK' && (!engineReady || lower)) ||
                (action === 'COUNTER_OFFER' && !card.decision?.variants.length)
              }
              onClick={() => setOpened({ action, card })}
            >
              {labels[action]}
            </Button>
          ))}
        </Group>
        <Modal
          opened={opened !== null}
          onClose={() => setOpened(null)}
          withCloseButton={false}
          closeOnClickOutside={false}
          closeOnEscape={false}
          title={opened ? labels[opened.action] : ''}
        >
          {opened ? (
            <ActionForm
              key={opened.action}
              action={opened.action}
              card={opened.card}
              stale={card.stale || card.version !== opened.card.version || !manual}
              onClose={() => setOpened(null)}
            />
          ) : null}
        </Modal>
      </Stack>
    </Paper>
  );
}

function ActionForm({
  action,
  card,
  stale,
  onClose,
}: {
  action: Action;
  card: BankApplicationCard;
  stale: boolean;
  onClose: () => void;
}) {
  const cache = useQueryClient();
  const navigate = useNavigate();
  const key = useActionKey();
  const busy = useRef(false);
  const [reason, setReason] = useState<BankInfoRequestReasonCode | ''>(
    action === 'INFO' ? 'UW_NEW_INFO' : '',
  );
  const [comment, setComment] = useState('');
  const [variant, setVariant] = useState('0');
  const [kind, setKind] = useState<BankInfoItem['kind']>('EXPLANATION');
  const [title, setTitle] = useState('');
  const [why, setWhy] = useState('');
  const [what, setWhat] = useState('');
  const [where, setWhere] = useState('');
  const [conflicted, setConflicted] = useState(false);
  const choice = card.decision?.variants[Number(variant)];
  const decisionAction =
    action === 'APPROVED' || action === 'REJECTED' || action === 'COUNTER_OFFER';
  const deviation = decisionAction && card.engineRecommendation?.outcome !== action;
  const min = card.decision?.requiredLevel === 'L2' || reason === 'UW_OTHER' ? 50 : 20;
  const needsReason = deviation || action === 'INFO';
  const valid =
    !stale &&
    (!needsReason || Boolean(reason)) &&
    (!deviation || comment.trim().length >= min) &&
    (action !== 'INFO' || (title.trim().length > 0 && why.trim().length > 0)) &&
    (action !== 'COUNTER_OFFER' || Boolean(choice));
  const mutation = useMutation({
    mutationFn: async () => {
      const options = key.request();
      if (action === 'RECHECK')
        return recheckBackofficeApplication(card.id, { expectedVersion: card.version }, options);
      if (action === 'INFO')
        return requestBackofficeInformation(
          card.id,
          {
            expectedVersion: card.version,
            reasonCode: reason as BankInfoRequestReasonCode,
            items: [
              {
                kind,
                title: title.trim(),
                whyText: why.trim(),
                what: what.trim(),
                where: where.trim(),
              },
            ],
          },
          options,
        );
      const terms: BankDecisionRequest['terms'] =
        action === 'REJECTED'
          ? null
          : {
              productCode:
                action === 'COUNTER_OFFER' && choice
                  ? choice.productCode
                  : (card.productCode ?? ''),
              amountRub:
                action === 'COUNTER_OFFER' && choice ? choice.amountRub : (card.amountRub ?? 0),
              termMonths:
                action === 'COUNTER_OFFER' && choice ? choice.termMonths : (card.termMonths ?? 0),
              ...(action === 'COUNTER_OFFER' && choice ? { ratePercent: choice.ratePercent } : {}),
            };
      return saveBackofficeDecision(
        card.id,
        {
          expectedVersion: card.version,
          engineDecisionId: card.engineDecisionId,
          outcome: action,
          terms,
          reasonCode: reason || null,
          comment: comment.trim() || null,
        },
        options,
      );
    },
    onSuccess: () => {
      key.reset();
      void cache.invalidateQueries({
        predicate: (q) =>
          q.queryKey.some((p) => typeof p === 'string' && p.includes('/backoffice/')),
      });
      void navigate('/bank', {
        state: {
          bankActionNotice:
            action === 'INFO' ? t.requested : action === 'RECHECK' ? t.checking : t.saved,
        },
      });
    },
    onError: (error) => {
      if (
        isAppError(error) &&
        ['VERSION_CONFLICT', 'INVALID_TRANSITION', 'ENGINE_DECISION_STALE'].includes(error.code)
      ) {
        setConflicted(true);
        void cache.invalidateQueries({
          predicate: (q) =>
            q.queryKey.some((p) => typeof p === 'string' && p.includes('/backoffice/')),
        });
      }
    },
  });
  const submit = async () => {
    if (!valid || conflicted || busy.current) return;
    busy.current = true;
    try {
      await mutation.mutateAsync();
    } catch {
      /* Ошибка показана ниже; сетевой повтор сохраняет тот же ключ и тело. */
      busy.current = false;
    }
  };
  const locked = mutation.isPending || (isAppError(mutation.error) && mutation.error.status === 0);
  const edit = (change: () => void) => {
    if (locked) return;
    key.reset();
    mutation.reset();
    change();
  };
  return (
    <Stack gap="sm">
      {stale || conflicted ? <Alert color="yellow">{t.changed}</Alert> : null}
      {action === 'RECHECK' ? <Text>{t.recheckHelp}</Text> : null}
      {action === 'APPROVED' ? (
        <Text>
          {productName(card.productCode)} · {formatMoney(card.amountRub)} ·{' '}
          {formatTermMonths(card.termMonths)}
        </Text>
      ) : null}
      {action === 'COUNTER_OFFER' ? (
        <NativeSelect
          label={t.variant}
          value={variant}
          disabled={locked}
          onChange={(e) => edit(() => setVariant(e.target.value))}
          data={
            card.decision?.variants.map((v, index) => ({
              value: String(index),
              label: `${productName(v.productCode)} · ${formatMoney(v.amountRub)} · ${formatTermMonths(v.termMonths)}${v.securityRequired ? ` · ${t.security}` : ''}`,
            })) ?? []
          }
        />
      ) : null}
      {action === 'INFO' ? (
        <>
          <NativeSelect
            label={t.taskKind}
            value={kind}
            disabled={locked}
            data={Object.entries(t.taskKinds).map(([value, label]) => ({ value, label }))}
            onChange={(e) => edit(() => setKind(e.target.value as BankInfoItem['kind']))}
          />
          <TextInput
            label={t.taskTitle}
            required
            maxLength={200}
            value={title}
            disabled={locked}
            onChange={(e) => edit(() => setTitle(e.target.value))}
          />
          <Textarea
            label={t.why}
            required
            maxLength={4000}
            value={why}
            disabled={locked}
            onChange={(e) => edit(() => setWhy(e.target.value))}
          />
          <TextInput
            label={t.what}
            maxLength={4000}
            value={what}
            disabled={locked}
            onChange={(e) => edit(() => setWhat(e.target.value))}
          />
          <TextInput
            label={t.where}
            maxLength={4000}
            value={where}
            disabled={locked}
            onChange={(e) => edit(() => setWhere(e.target.value))}
          />
          <Text size="xs">{t.expires}</Text>
        </>
      ) : null}
      {needsReason ? (
        <NativeSelect
          label={t.reason}
          required
          value={reason}
          data={reasons}
          disabled={locked}
          onChange={(e) => edit(() => setReason(e.target.value as BankInfoRequestReasonCode | ''))}
        />
      ) : null}
      {deviation ? (
        <Textarea
          label={t.comment}
          required
          description={fill(t.commentHelp, { min })}
          value={comment}
          maxLength={4000}
          disabled={locked}
          onChange={(e) => edit(() => setComment(e.target.value))}
        />
      ) : decisionAction ? (
        <Text size="sm">{t.agreement}</Text>
      ) : null}
      {mutation.isError ? <ProblemAlert error={mutation.error} /> : null}
      <Group justify="flex-end">
        <Button variant="subtle" disabled={mutation.isPending} onClick={onClose}>
          {t.cancel}
        </Button>
        <Button
          disabled={!valid || conflicted || mutation.isSuccess}
          loading={mutation.isPending}
          onClick={() => void submit()}
        >
          {t.confirm}
        </Button>
      </Group>
    </Stack>
  );
}
