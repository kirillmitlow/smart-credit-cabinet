import { http } from 'msw';
import { fireEvent, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it, vi } from 'vitest';
import { blockingA11yViolations } from '@/test/a11y';
import { renderWithProviders } from '@/test/render';
import { server } from '@/test/server';
import { documentTexts as dt } from '@/texts/documents';
import { DocumentFiles } from './DocumentFiles';

const area = () => screen.getByRole('group', { name: dt.dropArea });
const drop = (files: File[]) => fireEvent.drop(area(), { dataTransfer: { files } });

describe('T-424: перетаскивание и выбор файла', () => {
  it('передаёт выбранный перетаскиванием оригинал с заявкой и задачей, без автоматической отправки', async () => {
    let received: FormData | null = null;
    const original = globalThis.fetch;
    vi.spyOn(globalThis, 'fetch').mockImplementation(async (input, init) => {
      const url = typeof input === 'string' ? input : input instanceof URL ? input.href : input.url;
      if (url.endsWith('/api/documents') && init?.method === 'POST') {
        received = init.body as FormData;
        return Response.json({ code: 'TEST_UPLOAD_FAILURE' }, { status: 503 });
      }
      return original(input, init);
    });
    renderWithProviders(<DocumentFiles applicationId="app-1" taskId="task-1" />);
    const file = new File(['original statement'], 'ВЫПИСКА.TXT', { type: 'text/plain' });
    drop([file]);
    expect(received).toBeNull();
    await userEvent.click(screen.getByRole('button', { name: dt.upload }));
    await waitFor(() => expect(received).not.toBeNull());
    expect(received!.get('file')).toBe(file);
    expect(received!.get('applicationId')).toBe('app-1');
    expect(received!.get('taskId')).toBe('task-1');
    expect(received!.get('kind')).toBe('BANK_STATEMENT_1C');
  });

  it.each([
    { name: 'bad.exe', size: 1, message: dt.fileTypeError },
    { name: 'empty.txt', size: 0, message: dt.emptyFile },
    { name: 'large.txt', size: 5 * 1024 * 1024 + 1, message: dt.statementTooLarge },
    { name: 'large.pdf', size: 10 * 1024 * 1024 + 1, message: dt.pdfTooLarge },
  ])('объясняет отказ до запроса на сервер: $name', async ({ name, size, message }) => {
    renderWithProviders(<DocumentFiles applicationId="app-1" />);
    const file = new File(['a'], name);
    Object.defineProperty(file, 'size', { value: size });
    drop([file]);
    expect(await screen.findByRole('alert')).toHaveTextContent(message);
    expect(screen.getByRole('button', { name: dt.upload })).toBeDisabled();
  });

  it('не выбирает молча первый из нескольких файлов и не принимает файл в закрытую задачу', async () => {
    const { unmount } = renderWithProviders(<DocumentFiles applicationId="app-1" />);
    const file = new File(['file'], 'statement.txt');
    drop([file, file]);
    expect(await screen.findByRole('alert')).toHaveTextContent(dt.singleFile);
    expect(screen.getByRole('button', { name: dt.upload })).toBeDisabled();
    unmount();
    renderWithProviders(<DocumentFiles applicationId="app-1" disabled />);
    drop([file]);
    expect(screen.getByRole('button', { name: dt.upload })).toBeDisabled();
  });

  it('выбор доступен клавиатурой; очистка имеет русское имя и возвращает кнопку загрузки в неактивное состояние', async () => {
    const user = userEvent.setup();
    server.use(http.get('*/api/documents', () => Response.json([])));
    const { container } = renderWithProviders(<DocumentFiles applicationId="app-1" />);
    await waitFor(() => expect(screen.queryByLabelText(dt.loading)).not.toBeInTheDocument());
    await user.tab();
    expect(screen.getByLabelText(dt.attach)).toHaveFocus();
    await user.upload(
      container.querySelector('input[type="file"]') as HTMLInputElement,
      new File(['file'], 'statement.txt'),
    );
    expect(screen.getByRole('button', { name: dt.upload })).toBeEnabled();
    const clear = screen.getByRole('button', { name: dt.clearFile });
    clear.focus();
    await user.keyboard('{Enter}');
    expect(screen.getByRole('button', { name: dt.upload })).toBeDisabled();
    expect(await blockingA11yViolations(container)).toEqual([]);
  });
});
