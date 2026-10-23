import { useRef, useState } from 'react';
import {
  Alert,
  Button,
  Group,
  List,
  NativeSelect,
  NumberInput,
  Stack,
  Text,
  Textarea,
  Title,
} from '@mantine/core';
import { useMutation, useQueryClient } from '@tanstack/react-query';
import { useNavigate } from 'react-router';
import { isAppError } from '@/api/errors';
import { evaluateBackofficeOffer, saveBackofficeDecision } from '@/api/generated/api';
import type { BankApplicationCard } from '@/api/generated/model';
import { useActionKey } from '@/api/idempotency';
import { ProblemAlert } from '@/components/ProblemAlert';
import { formatMoney, formatPercent } from '@/lib/format';
import { fill, productNames } from '@/texts';
import { bankActions as t, bankManual as m } from '@/texts/bankActions';
import { bankNumber } from './bankFormatting';

const products = Object.entries(productNames).map(([value, label]) => ({ value, label }));
const reasons = [
  { value: '', label: t.chooseReason },
  ...Object.entries(t.reasonOptions).map(([value, label]) => ({ value, label })),
];

export function ManualOfferForm({
  card,
  stale,
  onClose,
}: {
  card: BankApplicationCard;
  stale: boolean;
  onClose: () => void;
}) {
  const cache = useQueryClient();
  const navigate = useNavigate();
  const key = useActionKey();
  const saving = useRef(false);
  const calculating = useRef(false);
  const [product, setProduct] = useState(card.productCode ?? 'WORKING_CAPITAL');
  const [amount, setAmount] = useState<string | number>(card.amountRub ?? '');
  const [term, setTerm] = useState<string | number>(card.termMonths ?? '');
  const [rate, setRate] = useState<string | number>('');
  const [reason, setReason] = useState('');
  const [comment, setComment] = useState('');
  const [conflicted, setConflicted] = useState(false);
  const conflict = (error: unknown) => {
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
  };
  const preview = useMutation({
    mutationFn: () =>
      evaluateBackofficeOffer(card.id, {
        expectedVersion: card.version,
        engineDecisionId: card.engineDecisionId ?? '',
        outcome: 'COUNTER_OFFER',
        terms: {
          productCode: product,
          amountRub: Number(amount),
          termMonths: Number(term),
          ratePercent: rate === '' ? null : Number(rate),
        },
        reasonCode: reason || null,
        comment: comment.trim() || null,
      }),
    onError: conflict,
  });
  const result = preview.data?.status === 200 ? preview.data.data : undefined;
  const save = useMutation({
    mutationFn: () =>
      saveBackofficeDecision(
        card.id,
        {
          expectedVersion: card.version,
          engineDecisionId: card.engineDecisionId,
          outcome: 'COUNTER_OFFER',
          evaluationRef: result?.evaluationRef,
          reasonCode: reason || null,
          comment: comment.trim() || null,
        },
        key.request(),
      ),
    onError: conflict,
    onSuccess: () => {
      key.reset();
      void cache.invalidateQueries({
        predicate: (q) =>
          q.queryKey.some((p) => typeof p === 'string' && p.includes('/backoffice/')),
      });
      void navigate('/bank', { state: { bankActionNotice: t.saved } });
    },
  });
  const unresolvedSave = isAppError(save.error) && save.error.status === 0;
  const locked = preview.isPending || save.isPending || unresolvedSave || save.isSuccess;
  const valid =
    !stale &&
    !conflicted &&
    Boolean(card.engineDecisionId) &&
    Number.isSafeInteger(Number(amount)) &&
    Number(amount) > 0 &&
    Number.isSafeInteger(Number(term)) &&
    Number(term) > 0 &&
    (rate === '' || (Number.isFinite(Number(rate)) && Number(rate) > 0 && Number(rate) <= 100));
  const edit = (change: () => void) => {
    if (locked) return;
    preview.reset();
    save.reset();
    key.reset();
    change();
  };
  const calculate = async () => {
    if (!valid || calculating.current || locked) return;
    calculating.current = true;
    try {
      await preview.mutateAsync();
    } catch {
      /* Сообщение об ошибке ниже. */
    } finally {
      calculating.current = false;
    }
  };
  const submit = async () => {
    if (!valid || !result?.allowed || !result.evaluationRef || saving.current) return;
    saving.current = true;
    try {
      await save.mutateAsync();
    } catch {
      saving.current = false;
    }
  };
  return (
    <Stack gap="sm">
      <Text size="sm">{m.intro}</Text>
      {stale || conflicted ? <Alert color="yellow">{t.changed}</Alert> : null}
      <NativeSelect
        label={m.product}
        data={products}
        value={product}
        disabled={locked}
        onChange={(e) => edit(() => setProduct(e.target.value))}
      />
      <NumberInput
        label={m.amount}
        value={amount}
        onChange={(v) => edit(() => setAmount(v))}
        min={1}
        max={Number.MAX_SAFE_INTEGER}
        allowDecimal={false}
        thousandSeparator=" "
        disabled={locked}
      />
      <NumberInput
        label={m.term}
        value={term}
        onChange={(v) => edit(() => setTerm(v))}
        min={1}
        allowDecimal={false}
        disabled={locked}
      />
      <NumberInput
        label={m.rate}
        description={m.rateHint}
        value={rate}
        onChange={(v) => edit(() => setRate(v))}
        min={0}
        max={100}
        decimalScale={4}
        disabled={locked}
      />
      <NativeSelect
        label={t.reason}
        value={reason}
        data={reasons}
        disabled={locked}
        onChange={(e) => edit(() => setReason(e.target.value))}
      />
      <Textarea
        label={t.comment}
        value={comment}
        maxLength={4000}
        disabled={locked}
        onChange={(e) => edit(() => setComment(e.target.value))}
      />
      <Button
        variant="light"
        loading={preview.isPending}
        disabled={!valid || locked}
        onClick={() => void calculate()}
      >
        {m.calculate}
      </Button>
      {preview.isError ? <ProblemAlert error={preview.error} /> : null}
      {result ? (
        <Stack gap="xs" aria-live="polite" data-testid="bank-manual-result">
          <Title order={3} size="h4">
            {m.result}
          </Title>
          <Alert color={result.allowed ? 'green' : 'yellow'}>
            {result.allowed ? m.allowed : m.denied}
          </Alert>
          <Text>{fill(t.requiredLevel, { level: result.requiredLevel })}</Text>
          <Text size="sm">{fill(m.minComment, { min: result.minCommentChars })}</Text>
          <Text>
            {m.rate}: {formatPercent(result.ratePercent)}
          </Text>
          <Text>
            {m.corridor}: {formatPercent(result.corridorMinPercent)}…
            {formatPercent(result.corridorMaxPercent)}
          </Text>
          <Text>
            {m.payment}: {formatMoney(result.paymentRub)}
          </Text>
          <Text>
            {m.lastPayment}: {formatMoney(result.lastPaymentRub)}
          </Text>
          <Text>
            {m.overpayment}: {formatMoney(result.overpaymentRub)}
          </Text>
          <Text>
            {m.dscr}: {bankNumber(result.dscr)} · {m.stress}: {bankNumber(result.stressDscr)}
          </Text>
          {result.violations.length ? (
            <List>
              {result.violations.map((v, index) => (
                <List.Item key={`${v.code}-${index}`}>
                  {Object.hasOwn(m.violations, v.code)
                    ? m.violations[v.code as keyof typeof m.violations]
                    : m.notAllowed}{' '}
                  <Text span size="xs">
                    ({v.code})
                  </Text>
                </List.Item>
              ))}
            </List>
          ) : null}
        </Stack>
      ) : null}
      {save.isError ? <ProblemAlert error={save.error} /> : null}
      <Group justify="flex-end">
        <Button variant="subtle" disabled={preview.isPending || save.isPending} onClick={onClose}>
          {t.cancel}
        </Button>
        <Button
          loading={save.isPending}
          disabled={
            !valid ||
            !result?.allowed ||
            !result.evaluationRef ||
            preview.isPending ||
            save.isSuccess
          }
          onClick={() => void submit()}
        >
          {m.save}
        </Button>
      </Group>
    </Stack>
  );
}
