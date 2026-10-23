import { Stack, Table, Text } from '@mantine/core';
import { formatMoney } from '@/lib/format';
import { fill } from '@/texts';
import { bankCard as t } from '@/texts/bank';

/** Раскрываем исходные данные таблицей; значения не превращаются в HTML или внешние ссылки. */
export function BankSnapshotData({ value, name = '' }: { value: unknown; name?: string }) {
  if (value === null || value === undefined) return <Text size="sm">{t.noData}</Text>;
  if (typeof value === 'boolean') return <Text size="sm">{value ? t.yes : t.no}</Text>;
  if (typeof value === 'string' || typeof value === 'number') {
    return (
      <Text size="sm" style={{ overflowWrap: 'anywhere' }}>
        {typeof value === 'number' && name.endsWith('Rub') ? formatMoney(value) : String(value)}
      </Text>
    );
  }
  if (Array.isArray(value))
    return (
      <details>
        <summary>{fill(t.entries, { count: value.length })}</summary>
        <Stack gap="sm">
          {value.map((entry: unknown, index) => (
            <BankSnapshotData key={index} value={entry} />
          ))}
        </Stack>
      </details>
    );
  if (typeof value !== 'object') return null;
  return (
    <Table withRowBorders={false} verticalSpacing={3}>
      <Table.Tbody>
        {Object.entries(value as Record<string, unknown>).map(([key, entry]) => (
          <Table.Tr key={key}>
            <Table.Th scope="row" fw={500} style={{ verticalAlign: 'top' }}>
              {Object.prototype.hasOwnProperty.call(t.snapshotKeys, key)
                ? t.snapshotKeys[key as keyof typeof t.snapshotKeys]
                : key}
            </Table.Th>
            <Table.Td>
              <BankSnapshotData value={entry} name={key} />
            </Table.Td>
          </Table.Tr>
        ))}
      </Table.Tbody>
    </Table>
  );
}
