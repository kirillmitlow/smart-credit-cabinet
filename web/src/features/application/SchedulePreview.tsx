import { Table, Text } from '@mantine/core';
import type { VariantOut } from '@/api/generated/model';
import { formatMoney } from '@/lib/format';
import { decision as t } from '@/texts';

/** Первые три платежа и последний из снимка сервера; полный график будет в договоре */
export function SchedulePreview({ terms }: { terms: VariantOut }) {
  if (!terms.schedulePreview.length) return null;
  return (
    <details>
      <summary>{t.schedule}</summary>
      <Text size="sm" c="dimmed" my="xs">
        {t.scheduleHint}
      </Text>
      <Table.ScrollContainer minWidth={420}>
        <Table captionSide="top">
          <Table.Caption>{t.schedule}</Table.Caption>
          <Table.Thead>
            <Table.Tr>
              <Table.Th>{t.paymentNumber}</Table.Th>
              <Table.Th>{t.principal}</Table.Th>
              <Table.Th>{t.interest}</Table.Th>
              <Table.Th>{t.total}</Table.Th>
            </Table.Tr>
          </Table.Thead>
          <Table.Tbody>
            {terms.schedulePreview.map((row) => (
              <Table.Tr key={row.number}>
                <Table.Td>{row.number}</Table.Td>
                <Table.Td>{formatMoney(row.principalRub)}</Table.Td>
                <Table.Td>{formatMoney(row.interestRub)}</Table.Td>
                <Table.Td>{formatMoney(row.paymentRub)}</Table.Td>
              </Table.Tr>
            ))}
          </Table.Tbody>
        </Table>
      </Table.ScrollContainer>
    </details>
  );
}
