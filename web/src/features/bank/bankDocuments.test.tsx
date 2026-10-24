import { screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it } from 'vitest';
import type { BankDocument } from '@/api/generated/model';
import { blockingA11yViolations } from '@/test/a11y';
import { makeBankCard } from '@/test/bankFactory';
import { renderWithProviders } from '@/test/render';
import { documentTexts as dt } from '@/texts/documents';
import { BankEvidencePanels } from './BankEvidencePanels';

function statement(changes: Partial<BankDocument> = {}): BankDocument {
  return {
    id: 'doc-1',
    taskId: 'task-1',
    kind: 'BANK_STATEMENT_1C',
    origin: 'DEMO_GENERATED',
    filename: 'statement.txt',
    mime: 'text/plain',
    sizeBytes: 100,
    sha256: 'a'.repeat(64),
    parseStatus: 'PARSED',
    parseError: null,
    confirmedAt: null,
    createdAt: '2026-10-21T12:00:00Z',
    cancelledAt: null,
    ...changes,
  };
}

describe('T-335/T-431: исходные документы сотрудника банка', () => {
  it('разделяет PDF-просмотр и скачивание тех же байтов, объясняет ручную проверку и показывает хеш', async () => {
    const doc = statement({
      kind: 'CONTRACT',
      mime: 'application/pdf',
      filename: 'contract.pdf',
      origin: 'UPLOADED',
    });
    const { container } = renderWithProviders(
      <BankEvidencePanels card={makeBankCard({ documents: [doc] })} />,
    );
    const area = within(screen.getByTestId('bank-documents'));
    const preview = area.getByRole('link', { name: doc.filename });
    expect(preview).toHaveAttribute('href', '/api/documents/doc-1/download?zone=bank&preview=true');
    expect(preview).toHaveAttribute('target', '_blank');
    expect(area.getByRole('link', { name: `${dt.download}: ${doc.filename}` })).toHaveAttribute(
      'href',
      '/api/documents/doc-1/download?zone=bank',
    );
    expect(area.getByText(dt.kinds.CONTRACT!)).toBeInTheDocument();
    expect(area.getByText(dt.pdfReview)).toBeInTheDocument();
    await userEvent.click(area.getByText(dt.hash));
    expect(area.getByText(doc.sha256)).toBeVisible();
    expect(await blockingA11yViolations(container)).toEqual([]);
  });

  it.each([
    { parseStatus: 'PENDING', text: dt.pending },
    { parseStatus: 'PROCESSING', text: dt.processing },
    { parseStatus: 'PARSED', text: dt.bankNotConfirmed },
    { parseStatus: 'FAILED', text: dt.parseErrors.INN_MISMATCH!, parseError: 'INN_MISMATCH' },
    { parseStatus: 'FAILED', text: dt.bankFailed, parseError: 'UNKNOWN_FAILURE' },
  ])('показывает реальное состояние выписки: $parseStatus', ({ text, ...changes }) => {
    renderWithProviders(
      <BankEvidencePanels card={makeBankCard({ documents: [statement(changes)] })} />,
    );
    const area = within(screen.getByTestId('bank-documents'));
    expect(area.getByText(text)).toBeInTheDocument();
    expect(screen.getByTestId('bank-documents')).toHaveTextContent(dt.demoGenerated);
    expect(area.queryByText(dt.pdfReview)).not.toBeInTheDocument();
  });

  it('сохраняет историю замены и явно отличает утверждение клиента от проверки банком', () => {
    renderWithProviders(
      <BankEvidencePanels
        card={makeBankCard({
          documents: [
            statement({
              confirmedAt: '2026-10-21T12:05:00Z',
              cancelledAt: '2026-10-21T13:00:00Z',
            }),
          ],
        })}
      />,
    );
    const area = within(screen.getByTestId('bank-documents'));
    expect(area.getByText(dt.replaced)).toBeInTheDocument();
    expect(area.getByText(new RegExp(dt.bankConfirmed))).toBeInTheDocument();
  });
});
