import { screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { http } from 'msw';
import { describe, expect, it } from 'vitest';
import { blockingA11yViolations } from '@/test/a11y';
import {
  makeApplication,
  makeCompanyChoice,
  makeMe,
  makeConsents,
  problemResponse,
} from '@/test/factories';
import { renderApp } from '@/test/render';
import { mockSessions } from '@/test/sessions';
import { server } from '@/test/server';
import { applicationForm, errorTexts } from '@/texts';

const f = applicationForm;

interface PatchBody {
  version: number;
  productCode?: string;
  amountRub?: number;
  termMonths?: number;
}

/** Сервер-черновик в памяти: PATCH увеличивает версию, как настоящий api */
function mockDraft(
  initial = makeApplication({ productCode: null, amountRub: null, termMonths: null }),
) {
  let current = initial;
  const patches: PatchBody[] = [];
  server.use(
    http.get('*/api/applications/app-1', () => Response.json(current)),
    http.get('*/api/applications/app-1/consents', () =>
      Response.json(makeConsents({ allSigned: true, items: [] })),
    ),
    http.patch('*/api/applications/app-1/draft', async ({ request }) => {
      const body = (await request.json()) as PatchBody;
      patches.push(body);
      if (body.version !== current.version) {
        return problemResponse({ status: 409, code: 'VERSION_CONFLICT' });
      }
      current = { ...current, ...body, version: current.version + 1 };
      return Response.json(current);
    }),
  );
  return {
    patches,
    set: (next: typeof current) => {
      current = next;
    },
    get: () => current,
  };
}

const amountField = () => screen.getByLabelText(/Сумма/);
const termField = () => screen.getByLabelText(new RegExp(f.conditions.term));

describe('заявка по шагам: Условия и автосохранение', () => {
  it('шаг в адресе, пять шагов, доступность', async () => {
    mockSessions({ client: makeMe() });
    mockDraft();
    const { container } = renderApp('/applications/app-1/edit/1');
    expect(
      await screen.findByRole('heading', { level: 1, name: /Шаг 1 из 5: Условия/ }),
    ).toBeInTheDocument();
    expect(screen.getByRole('navigation', { name: f.stepsLabel })).toBeInTheDocument();
    expect(
      screen
        .getAllByRole('link', { name: f.conditions.pickWizard })
        .map((a) => a.getAttribute('href')),
    ).toEqual(['/wizard', '/wizard']);
    expect(await blockingA11yViolations(container)).toEqual([]);
  });

  it('автосохранение через паузу: PATCH с version, затем «Сохранено в …»; платёж пересчитывается', async () => {
    const user = userEvent.setup();
    mockSessions({ client: makeMe() });
    const draft = mockDraft();
    renderApp('/applications/app-1/edit/1');
    await user.click((await screen.findAllByLabelText(/^Продукт/))[0]!);
    await user.click(await screen.findByRole('option', { name: 'Экспресс-кредит', hidden: true }));
    await user.type(amountField(), '500000');
    await user.type(termField(), '12');

    expect(draft.patches).toHaveLength(0); // пауза ещё не прошла
    await waitFor(() => expect(draft.patches).toHaveLength(1), { timeout: 3000 });
    expect(draft.patches[0]).toMatchObject({
      version: 1,
      productCode: 'EXPRESS',
      amountRub: 500000,
      termMonths: 12,
    });
    expect(await screen.findByText(/Сохранено в \d\d:\d\d/)).toBeInTheDocument();
    expect(screen.getByTestId('payment')).toHaveTextContent('₽');
    expect(screen.getByTestId('payment')).toHaveTextContent(f.conditions.paymentNote);
  });

  it('неверная сумма: ошибка у поля, в черновик она не уходит', async () => {
    const user = userEvent.setup();
    mockSessions({ client: makeMe() });
    const draft = mockDraft();
    renderApp('/applications/app-1/edit/1');
    await user.type(await screen.findByLabelText(/Сумма/), '2000000000');
    expect(await screen.findByText(f.validation.amountTooBig)).toBeInTheDocument();
    await user.type(termField(), '12');
    await waitFor(() => expect(draft.patches).toHaveLength(1), { timeout: 3000 });
    expect(draft.patches[0]).not.toHaveProperty('amountRub');
    expect(draft.patches[0]).toMatchObject({ termMonths: 12 });
  });

  it('VERSION_CONFLICT: мягкое сообщение и «Обновить» подтягивает свежую заявку', async () => {
    const user = userEvent.setup();
    mockSessions({ client: makeMe() });
    const draft = mockDraft();
    renderApp('/applications/app-1/edit/1');
    await user.type(await screen.findByLabelText(/Сумма/), '300000');
    // другая вкладка успела изменить заявку
    draft.set(
      makeApplication({ version: 5, amountRub: 700_000, productCode: 'EXPRESS', termMonths: 18 }),
    );
    expect(
      await screen.findByText(errorTexts.VERSION_CONFLICT.text, undefined, { timeout: 3000 }),
    ).toBeInTheDocument();

    await user.click(screen.getByRole('button', { name: errorTexts.VERSION_CONFLICT.action }));
    await waitFor(() =>
      expect(screen.queryByText(errorTexts.VERSION_CONFLICT.text)).not.toBeInTheDocument(),
    );
    expect((amountField() as HTMLInputElement).value.replace(/\s/g, '')).toBe('700000');
    expect(termField()).toHaveValue('18');
  });

  it('шаг 2 — карточка компании; на шаге 4 загружены согласия', async () => {
    const user = userEvent.setup();
    mockSessions({ client: makeMe() });
    mockDraft(makeApplication());
    renderApp('/applications/app-1/edit/1');
    await screen.findByRole('heading', { level: 1, name: /Шаг 1 из 5/ });
    await user.click(screen.getByRole('button', { name: f.next }));
    expect(
      await screen.findByRole('heading', { level: 1, name: /Шаг 2 из 5: Данные компании/ }),
    ).toBeInTheDocument();
    expect(window.location.pathname).toBe('/applications/app-1/edit/2');
    await user.click(screen.getByRole('button', { name: f.next }));
    await user.click(await screen.findByRole('button', { name: f.next }));
    expect(
      await screen.findByRole('heading', { level: 1, name: /Шаг 4 из 5: Согласия/ }),
    ).toBeInTheDocument();
    expect(
      await screen.findByRole('heading', { name: 'Согласия на проверку заявки' }),
    ).toBeInTheDocument();
    expect(screen.queryByTestId('later-step')).not.toBeInTheDocument();
  });

  it('несуществующий шаг и чужая заявка', async () => {
    mockSessions({ client: makeMe() });
    mockDraft();
    renderApp('/applications/app-1/edit/9');
    expect(
      await screen.findByRole('heading', { level: 1, name: 'Не нашли такую страницу' }),
    ).toBeInTheDocument();
  });

  it('заявка не найдена: «Не нашли такую заявку»', async () => {
    mockSessions({ client: makeMe() });
    server.use(
      http.get('*/api/applications/app-1', () =>
        problemResponse({ status: 404, code: 'NOT_FOUND' }),
      ),
    );
    renderApp('/applications/app-1/edit/1');
    expect(
      await screen.findByRole('heading', { level: 1, name: 'Не нашли такую заявку' }),
    ).toBeInTheDocument();
  });

  it('отправленная заявка не редактируется: открывается её страница', async () => {
    mockSessions({ client: makeMe() });
    server.use(
      http.get('*/api/applications/app-1', () =>
        Response.json(makeApplication({ status: 'CHECKING', allowedActions: ['WITHDRAW'] })),
      ),
    );
    renderApp('/applications/app-1/edit/1');
    await waitFor(() => expect(window.location.pathname).toBe('/applications/app-1'));
  });
});

describe('заявка по шагам: Проверьте и отправьте', () => {
  it('сводка, отправка с Idempotency-Key, двойной клик — одна отправка, переход на страницу заявки', async () => {
    const user = userEvent.setup();
    mockSessions({ client: makeMe() });
    mockDraft(makeApplication());
    const keys: (string | null)[] = [];
    server.use(
      http.post('*/api/applications/app-1/submit', async ({ request }) => {
        keys.push(request.headers.get('Idempotency-Key'));
        await new Promise((resolve) => setTimeout(resolve, 100));
        return Response.json(
          makeApplication({
            status: 'SUBMITTED',
            submittedAt: '2026-10-21T09:04:00Z',
            allowedActions: ['WITHDRAW'],
          }),
        );
      }),
    );
    renderApp('/applications/app-1/edit/5');
    expect(await screen.findByTestId('review-summary')).toHaveTextContent('Экспресс-кредит');
    expect(screen.getByTestId('review-summary')).toHaveTextContent('12 месяцев');
    await user.dblClick(screen.getByRole('button', { name: f.review.submit }));
    await waitFor(() => expect(window.location.pathname).toBe('/applications/app-1'));
    expect(keys).toHaveLength(1);
    expect(keys[0]).toBeTruthy();
  });

  it('не хватает данных: кнопка неактивна, написано, чего нет', async () => {
    mockSessions({ client: makeMe() });
    mockDraft(makeApplication({ amountRub: null }));
    renderApp('/applications/app-1/edit/5');
    expect(await screen.findByText(/Чтобы отправить, заполните: сумму/)).toBeInTheDocument();
    expect(screen.getByRole('button', { name: f.review.submit })).toBeDisabled();
  });

  it('CONSENT_REQUIRED: объяснение и возврат к согласиям (шаг 4)', async () => {
    const user = userEvent.setup();
    mockSessions({ client: makeMe() });
    mockDraft(makeApplication());
    server.use(
      http.post('*/api/applications/app-1/submit', () =>
        problemResponse({ status: 422, code: 'CONSENT_REQUIRED' }),
      ),
    );
    renderApp('/applications/app-1/edit/5');
    await user.click(await screen.findByRole('button', { name: f.review.submit }));
    expect(await screen.findByText(errorTexts.CONSENT_REQUIRED.text)).toBeInTheDocument();
    await user.click(screen.getByRole('button', { name: errorTexts.CONSENT_REQUIRED.action }));
    expect(
      await screen.findByRole('heading', { level: 1, name: /Шаг 4 из 5/ }),
    ).toBeInTheDocument();
  });

  it('DUPLICATE_APPLICATION: ведёт к уже идущей заявке', async () => {
    const user = userEvent.setup();
    mockSessions({ client: makeMe() });
    mockDraft(makeApplication());
    const other = makeApplication({
      id: 'app-0',
      status: 'CHECKING',
      allowedActions: ['WITHDRAW'],
    });
    server.use(
      http.post('*/api/applications/app-1/submit', () =>
        problemResponse({ status: 409, code: 'DUPLICATE_APPLICATION' }),
      ),
      http.get('*/api/applications', () =>
        Response.json({ items: [makeApplication(), other], nextCursor: null }),
      ),
      http.get('*/api/applications/app-0', () => Response.json(other)),
    );
    renderApp('/applications/app-1/edit/5');
    await user.click(await screen.findByRole('button', { name: f.review.submit }));
    expect(await screen.findByText(errorTexts.DUPLICATE_APPLICATION.text)).toBeInTheDocument();
    await user.click(screen.getByRole('button', { name: errorTexts.DUPLICATE_APPLICATION.action }));
    await waitFor(() => expect(window.location.pathname).toBe('/applications/app-0'));
  });

  it('бухгалтер может отправить, а договор подпишет руководитель', async () => {
    mockSessions({ client: makeMe({ companies: [makeCompanyChoice({}, 'ACCOUNTANT')] }) });
    mockDraft(makeApplication());
    renderApp('/applications/app-1/edit/5');
    expect(await screen.findByText(f.review.accountantNote)).toBeInTheDocument();
    await waitFor(() =>
      expect(screen.getByRole('button', { name: f.review.submit })).toBeEnabled(),
    );
  });

  it('нет права отправлять (нет SUBMIT в allowedActions): кнопки нет', async () => {
    mockSessions({ client: makeMe() });
    mockDraft(makeApplication({ allowedActions: [] }));
    renderApp('/applications/app-1/edit/5');
    expect(await screen.findByText(f.review.noSubmitAction)).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: f.review.submit })).not.toBeInTheDocument();
  });
});
