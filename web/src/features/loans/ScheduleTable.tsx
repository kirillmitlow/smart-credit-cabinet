import { Badge, Group, Table, Text } from '@mantine/core';
import type { LoanPaymentOut } from '@/api/generated/model';
import { formatDate, formatMoney } from '@/lib/format';
import { fill, loansTexts as t } from '@/texts';
import { scheduleTotals, withBalances } from './loanModel';

export interface ScheduleTableProps {
  contractNumber: string;
  schedule: LoanPaymentOut[];
  amountRub: number;
  /** Номер ближайшего платежа: строка помечается */
  nextSeq: number | null;
}

/** График платежей: дата, платёж, основной долг, проценты, остаток; внизу итог (долг + проценты) */
export function ScheduleTable({
  contractNumber,
  schedule,
  amountRub,
  nextSeq,
}: ScheduleTableProps) {
  const rows = withBalances(schedule, amountRub);
  const totals = scheduleTotals(schedule);
  const c = t.detail.columns;
  return (
    <Table.ScrollContainer minWidth={560}>
      <Table striped={false} verticalSpacing="xs" data-testid="schedule-table">
        <Table.Caption>{fill(t.detail.scheduleCaption, { number: contractNumber })}</Table.Caption>
        <Table.Thead>
          <Table.Tr>
            <Table.Th scope="col">{c.number}</Table.Th>
            <Table.Th scope="col">{c.date}</Table.Th>
            <Table.Th scope="col" ta="right">
              {c.payment}
            </Table.Th>
            <Table.Th scope="col" ta="right">
              {c.principal}
            </Table.Th>
            <Table.Th scope="col" ta="right">
              {c.interest}
            </Table.Th>
            <Table.Th scope="col" ta="right">
              {c.balance}
            </Table.Th>
          </Table.Tr>
        </Table.Thead>
        <Table.Tbody>
          {rows.map((row) => (
            <Table.Tr key={row.seq} data-testid="schedule-row" data-next={row.seq === nextSeq}>
              <Table.Td>{row.seq}</Table.Td>
              <Table.Td>
                <Group gap="xs" wrap="nowrap">
                  <Text span>{formatDate(row.dueDate)}</Text>
                  {row.seq === nextSeq ? (
                    <Badge variant="light" size="sm">
                      {t.detail.nextBadge}
                    </Badge>
                  ) : null}
                </Group>
              </Table.Td>
              <Table.Td ta="right">{formatMoney(row.totalRub)}</Table.Td>
              <Table.Td ta="right">{formatMoney(row.principalRub)}</Table.Td>
              <Table.Td ta="right">{formatMoney(row.interestRub)}</Table.Td>
              <Table.Td ta="right">{formatMoney(row.balanceRub)}</Table.Td>
            </Table.Tr>
          ))}
        </Table.Tbody>
        <Table.Tfoot>
          <Table.Tr data-testid="schedule-total">
            <Table.Th scope="row" colSpan={2}>
              {t.detail.total}
            </Table.Th>
            <Table.Th ta="right">{formatMoney(totals.totalRub)}</Table.Th>
            <Table.Th ta="right">{formatMoney(totals.principalRub)}</Table.Th>
            <Table.Th ta="right">{formatMoney(totals.interestRub)}</Table.Th>
            <Table.Td />
          </Table.Tr>
        </Table.Tfoot>
      </Table>
    </Table.ScrollContainer>
  );
}
