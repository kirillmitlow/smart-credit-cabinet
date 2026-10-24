import { useRef, useState } from 'react';
import { Button, Checkbox, Stack, Table, Text, TextInput } from '@mantine/core';
import { useQueryClient } from '@tanstack/react-query';
import { getListDocumentsQueryKey, useConfirmStatement } from '@/api/generated/api';
import type { DocumentOut } from '@/api/generated/model';
import { useActionKey } from '@/api/idempotency';
import { ProblemAlert } from '@/components/ProblemAlert';
import { documentTexts as dt } from '@/texts/documents';

interface ReviewMonth {
  month: string;
  incoming: number;
  outgoing: number;
}

function reviewMonths(document: DocumentOut): ReviewMonth[] {
  const raw = document.parsed?.months;
  if (!Array.isArray(raw)) return [];
  return raw
    .filter((row) => row?.complete === true)
    .flatMap((row) => {
      const incoming = row.unclassifiedIncomingKopecks;
      const outgoing = row.outgoingKopecks - row.internalOutgoingKopecks;
      if (
        typeof row.month !== 'string' ||
        !Number.isSafeInteger(incoming) ||
        incoming < 0 ||
        !Number.isSafeInteger(row.outgoingKopecks) ||
        !Number.isSafeInteger(row.internalOutgoingKopecks) ||
        !Number.isSafeInteger(outgoing) ||
        outgoing < 0
      )
        return [];
      return [{ month: row.month, incoming, outgoing }];
    })
    .sort((a, b) => a.month.localeCompare(b.month))
    .slice(-24);
}

function rubles(cents: number): string {
  const exact = BigInt(cents);
  return `${exact / 100n}.${String(exact % 100n).padStart(2, '0')}`;
}

function kopecks(value: string): number | null {
  if (!/^[0-9]{1,14}(?:[.,][0-9]{1,2})?$/.test(value)) return null;
  const [whole, fraction = ''] = value.replace(',', '.').split('.');
  const amount = BigInt(whole!) * 100n + BigInt(fraction.padEnd(2, '0'));
  return amount <= BigInt(Number.MAX_SAFE_INTEGER) ? Number(amount) : null;
}

export function StatementConfirmation({
  document,
  disabled = false,
}: {
  document: DocumentOut;
  disabled?: boolean;
}) {
  const rows = reviewMonths(document);
  const [values, setValues] = useState<Record<string, string>>(() =>
    Object.fromEntries(rows.map((row) => [row.month, rubles(row.incoming)])),
  );
  const [acknowledged, setAcknowledged] = useState(false);
  const action = useActionKey();
  const confirm = useConfirmStatement({ request: action.request() });
  const client = useQueryClient();
  const busy = useRef(false);
  const amounts = rows.map((row) => ({
    month: row.month,
    businessIncomingKopecks: kopecks(values[row.month] ?? ''),
  }));
  const valid =
    rows.length >= 3 &&
    amounts.every(
      (amount, index) =>
        amount.businessIncomingKopecks !== null &&
        amount.businessIncomingKopecks <= rows[index]!.incoming,
    );
  const stored = document.parsed?.revenueConfirmation;
  const storedMonths =
    stored && typeof stored === 'object'
      ? (stored as { months?: Record<string, unknown> }).months
      : undefined;
  const confirmed = !!document.confirmedAt;
  const locked = disabled || confirmed || confirm.isPending;

  const send = async () => {
    if (!valid || !acknowledged || locked || busy.current) return;
    busy.current = true;
    try {
      const response = await confirm.mutateAsync({
        documentId: document.id,
        data: {
          sha256: document.sha256,
          acknowledged: true,
          months: amounts.map((row) => ({
            ...row,
            businessIncomingKopecks: row.businessIncomingKopecks!,
          })),
        },
      });
      if (response.status === 200) {
        action.reset();
        await client.invalidateQueries({
          queryKey: getListDocumentsQueryKey({ applicationId: document.applicationId }),
        });
      }
    } catch {
      // Keep the same assertion/key after a lost response. Editing starts a new action.
    } finally {
      busy.current = false;
    }
  };
  if (rows.length < 3) return <Text size="sm">{dt.reviewUnavailable}</Text>;
  return (
    <Stack gap="xs">
      <Text fw={600}>{dt.reviewTitle}</Text>
      <Text size="sm">{dt.reviewHelp}</Text>
      <Text size="xs" c="dimmed">
        {dt.reviewWindow}
      </Text>
      <Table.ScrollContainer minWidth={460}>
        <Table>
          <Table.Tbody>
            {rows.map((row) => {
              const amount = kopecks(values[row.month] ?? '');
              const invalid = amount === null || amount > row.incoming;
              const saved = storedMonths?.[row.month];
              return (
                <Table.Tr key={row.month}>
                  <Table.Td>
                    <Text size="sm">{row.month}</Text>
                    <Text size="xs">{dt.reviewLimit(rubles(row.incoming))}</Text>
                    <Text size="xs" c="dimmed">
                      {dt.reviewOutgoing(rubles(row.outgoing))}
                    </Text>
                  </Table.Td>
                  <Table.Td>
                    <TextInput
                      label={dt.reviewAmount(row.month)}
                      inputMode="decimal"
                      value={
                        confirmed && typeof saved === 'number' && Number.isSafeInteger(saved)
                          ? rubles(saved)
                          : (values[row.month] ?? '')
                      }
                      disabled={locked}
                      error={!confirmed && invalid ? dt.reviewAmountError : undefined}
                      onChange={(event) => {
                        const value = event.currentTarget.value;
                        setValues((previous) => ({ ...previous, [row.month]: value }));
                        action.reset();
                        confirm.reset();
                      }}
                    />
                  </Table.Td>
                </Table.Tr>
              );
            })}
          </Table.Tbody>
        </Table>
      </Table.ScrollContainer>
      {confirmed ? (
        <Text size="sm" role="status">
          {dt.confirmed}
        </Text>
      ) : (
        <>
          <Checkbox
            label={dt.reviewAck}
            checked={acknowledged}
            disabled={locked}
            onChange={(event) => {
              setAcknowledged(event.currentTarget.checked);
              action.reset();
              confirm.reset();
            }}
          />
          {confirm.error ? <ProblemAlert error={confirm.error} /> : null}
          <Button
            variant="default"
            disabled={!valid || !acknowledged || locked}
            loading={confirm.isPending}
            onClick={() => void send()}
          >
            {dt.reviewConfirm}
          </Button>
        </>
      )}
    </Stack>
  );
}
