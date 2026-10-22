import { screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { http } from 'msw';
import { describe, expect, it } from 'vitest';
import type { DraftPatch } from '@/api/generated/model';
import { blockingA11yViolations } from '@/test/a11y';
import { makeCompanyProfile, makeProfileField } from '@/test/companyProfileFactory';
import { makeApplication, makeMe, problemResponse } from '@/test/factories';
import { renderApp } from '@/test/render';
import { mockSessions } from '@/test/sessions';
import { server } from '@/test/server';
import { applicationForm, errorTexts } from '@/texts';
import { companyProfile as t } from '@/texts/companyProfile';

function draftServer() {
  let application = makeApplication({ draft: { otherStep: { untouched: true } } });
  const patches: DraftPatch[] = [];
  server.use(
    http.get('*/api/applications/app-1', () => Response.json(application)),
    http.patch('*/api/applications/app-1/draft', async ({ request }) => {
      const body = (await request.json()) as DraftPatch;
      patches.push(body);
      if (body.version !== application.version)
        return problemResponse({ status: 409, code: 'VERSION_CONFLICT' });
      application = {
        ...application,
        draft: { ...application.draft, ...body.answers },
        version: application.version + 1,
      };
      return Response.json(application);
    }),
  );
  return {
    patches,
    get: () => application,
    set: (next: typeof application) => {
      application = next;
    },
  };
}

describe('TS-001: Данные компании и происхождение полей', () => {
  it('берёт компанию заявки, показывает понятные значения; источник доступен с клавиатуры', async () => {
    const user = userEvent.setup();
    mockSessions({ client: makeMe({ activeCompanyId: 'different-company' }) });
    draftServer();
    const requested: string[] = [];
    server.use(
      http.get('*/api/companies/:id', ({ params }) => {
        requested.push(String(params.id));
        return Response.json(makeCompanyProfile());
      }),
    );
    const { container } = renderApp('/applications/app-1/edit/2');
    expect(await screen.findByLabelText(t.labels.name)).toHaveValue('ООО «Ромашка»');
    expect(requested).toEqual(['company-1']);
    expect(screen.getByLabelText(t.labels.status)).toHaveValue('Действует');
    expect(screen.getByLabelText(t.labels.taxRegime)).toHaveValue('УСН «Доходы»');
    expect(screen.getByLabelText(t.labels.isBankCustomer)).toHaveValue('Нет');
    expect(screen.getByLabelText(t.labels.inn)).toHaveAttribute('readonly');
    expect(screen.getByText(/заполнено полей: 6/)).toBeInTheDocument();
    const source = screen.getByRole('button', { name: /Откуда данные поля «Название/ });
    source.focus();
    await user.keyboard('{Enter}');
    expect(source).toHaveAttribute('aria-expanded', 'true');
    expect(
      within(await screen.findByRole('dialog', { hidden: true })).getByText(
        /Получено 22 октября, 12:00/,
      ),
    ).toBeInTheDocument();
    await user.keyboard('{Escape}');
    expect(source).toHaveAttribute('aria-expanded', 'false');
    expect(await blockingA11yViolations(container)).toEqual([]);
  });

  it('ручное дополнение сохраняется в черновик с версией, а официальные сведения остаются отдельно', async () => {
    const user = userEvent.setup();
    mockSessions({ client: makeMe() });
    const state = draftServer();
    renderApp('/applications/app-1/edit/2');
    const address = await screen.findByLabelText(t.labels.address);
    await user.clear(address);
    await user.type(address, 'Новый адрес');
    await user.click(screen.getByRole('button', { name: applicationForm.next }));
    await waitFor(() => expect(window.location.pathname).toBe('/applications/app-1/edit/3'));
    expect(state.patches).toEqual([
      { version: 1, answers: { companyFields: { address: 'Новый адрес' } } },
    ]);
    expect(state.get().draft.otherStep).toEqual({ untouched: true });
    await user.click(screen.getByRole('button', { name: applicationForm.back }));
    expect(await screen.findByLabelText(t.labels.address)).toHaveValue('Новый адрес');
    await user.click(screen.getByRole('button', { name: /Откуда данные поля «Адрес/ }));
    expect(await screen.findByText(/Значение из источника: Новосибирск/)).toBeInTheDocument();
  });

  it('DOWN не блокирует форму; обновление источников сохраняет дополнение клиента', async () => {
    const user = userEvent.setup();
    mockSessions({ client: makeMe() });
    draftServer();
    server.use(
      http.get('*/api/companies/:id', () =>
        Response.json(
          makeCompanyProfile({
            eligibility: 'UNCONFIRMED',
            fields: {
              name: makeProfileField({ value: null, confirmed: false, retrievedAt: null }),
            },
          }),
        ),
      ),
      http.get('*/api/companies/lookup/:inn', () => Response.json(makeCompanyProfile())),
    );
    renderApp('/applications/app-1/edit/2');
    const name = await screen.findByLabelText(t.labels.name);
    expect(screen.getByText(t.unconfirmed)).toBeInTheDocument();
    expect(name).toBeEnabled();
    await user.type(name, 'Уточнённое название');
    await user.click(screen.getByRole('button', { name: t.refresh }));
    await screen.findByLabelText(t.labels.address);
    expect(name).toHaveValue('Уточнённое название');
    expect(screen.getByText(t.manual)).toBeInTheDocument();
    await screen.findByText(/Сохранено в/, undefined, { timeout: 3000 });
  });

  it('чужая новая версия не затирается; «Обновить» заменяет локальное дополнение', async () => {
    const user = userEvent.setup();
    mockSessions({ client: makeMe() });
    const state = draftServer();
    renderApp('/applications/app-1/edit/2');
    await user.type(await screen.findByLabelText(t.labels.address), ' новое');
    state.set(
      makeApplication({ version: 5, draft: { companyFields: { address: 'Из другой вкладки' } } }),
    );
    await screen.findByText(errorTexts.VERSION_CONFLICT.text, undefined, { timeout: 3000 });
    await user.click(screen.getByRole('button', { name: errorTexts.VERSION_CONFLICT.action }));
    await waitFor(() =>
      expect(screen.getByLabelText(t.labels.address)).toHaveValue('Из другой вкладки'),
    );
    expect(state.patches).toHaveLength(1);
    expect(state.get().version).toBe(5);
  });

  it('не использует ручной ИНН из старого черновика', async () => {
    mockSessions({ client: makeMe() });
    const state = draftServer();
    state.set(
      makeApplication({ draft: { companyFields: { inn: '123', address: 'Адрес клиента' } } }),
    );
    renderApp('/applications/app-1/edit/2');
    expect(await screen.findByLabelText(t.labels.inn)).toHaveValue('7707083893');
    expect(screen.getByLabelText(t.labels.address)).toHaveValue('Адрес клиента');
  });
});
