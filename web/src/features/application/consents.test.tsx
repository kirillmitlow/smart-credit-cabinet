import { screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { http } from 'msw';
import { describe, expect, it } from 'vitest';
import type { ConsentsOut, SignConfirm, SignRequest } from '@/api/generated/model';
import { blockingA11yViolations } from '@/test/a11y';
import {
  makeApplication,
  makeConsent,
  makeConsents,
  makeMe,
  problemResponse,
} from '@/test/factories';
import { renderApp } from '@/test/render';
import { server } from '@/test/server';
import { mockSessions } from '@/test/sessions';
import { applicationForm, consents as t, errorTexts, fill } from '@/texts';

function mockConsents(initial = makeConsents()) {
  let view = initial;
  const requests: SignRequest[] = [];
  const confirmations: SignConfirm[] = [];
  mockSessions({ client: makeMe() });
  server.use(
    http.get('*/api/applications/app-1', () => Response.json(makeApplication())),
    http.get('*/api/applications/app-1/consents', () => Response.json(view)),
    http.post('*/api/applications/app-1/consents', async ({ request }) => {
      const body = (await request.json()) as SignRequest;
      requests.push(body);
      return Response.json({
        requestId: `code-${requests.length}`,
        expiresInSeconds: 300,
        demoCode: '123456',
        items: body.items,
      });
    }),
    http.post('*/api/applications/app-1/consents/sign', async ({ request }) => {
      const body = (await request.json()) as SignConfirm;
      confirmations.push(body);
      const signed = view.items
        .filter((item) =>
          body.items.some((ref) => ref.kind === item.kind && ref.subjectInn === item.subjectInn),
        )
        .map((item) => ({
          ...item,
          status: 'SIGNED' as const,
          signedAt: '2026-10-22T08:00:00Z',
          validUntil: '2027-04-22',
          consentId: 'cns-1',
        }));
      view = {
        ...view,
        items: view.items.map(
          (item) =>
            signed.find(
              (entry) => entry.kind === item.kind && entry.subjectInn === item.subjectInn,
            ) ?? item,
        ),
        pepRules: { ...view.pepRules, accepted: true },
      };
      view.allSigned = view.items.every((item) => item.status === 'SIGNED');
      return Response.json({ applicationId: 'app-1', signed, allSigned: view.allSigned });
    }),
  );
  return {
    requests,
    confirmations,
    set: (next: ConsentsOut) => {
      view = next;
    },
  };
}

async function selectAll(user: ReturnType<typeof userEvent.setup>) {
  await screen.findByRole('heading', { name: t.heading });
  for (const checkbox of screen.getAllByRole('checkbox')) await user.click(checkbox);
}

async function start(user: ReturnType<typeof userEvent.setup>) {
  await selectAll(user);
  expect(screen.getByRole('button', { name: t.requestCode })).toBeEnabled();
  await user.click(screen.getByRole('button', { name: t.requestCode }));
  await screen.findByLabelText(new RegExp(t.codeLabel));
}

describe('согласия заявки (T-419)', () => {
  it('пустые отдельные галочки, тексты и версии до подписи, доступность', async () => {
    mockConsents();
    const { container } = renderApp('/applications/app-1/edit/4');
    await screen.findByRole('heading', { name: t.heading });
    expect(screen.getAllByRole('checkbox')).toHaveLength(4);
    screen.getAllByRole('checkbox').forEach((checkbox) => expect(checkbox).not.toBeChecked());
    expect(screen.getByRole('button', { name: t.requestCode })).toBeDisabled();
    const user = userEvent.setup();
    await user.click(screen.getAllByText(t.text)[0]!);
    expect(screen.getAllByText('Согласие на запрос кредитной истории.')[0]).toBeVisible();
    expect(screen.getAllByText(fill(t.version, { version: 'bki-v1' }))[0]).toBeVisible();
    expect(await blockingA11yViolations(container)).toEqual([]);
  });

  it('TS-076: один код подписывает точный выбранный пакет без открытия текста', async () => {
    const user = userEvent.setup();
    const state = mockConsents();
    renderApp('/applications/app-1/edit/4');
    await start(user);
    expect(state.requests).toEqual([
      {
        items: makeConsents().items.map(({ kind, subjectInn }) => ({ kind, subjectInn })),
        acceptPepRules: true,
      },
    ]);
    expect(screen.getByTestId('consent-demo-code')).toHaveTextContent(t.demoHint);
    screen.getAllByRole('checkbox').forEach((checkbox) => expect(checkbox).toBeDisabled());
    await user.type(screen.getByLabelText(new RegExp(t.codeLabel)), '123456');
    await user.dblClick(screen.getByRole('button', { name: t.sign }));
    expect(await screen.findByText(t.allSigned)).toBeInTheDocument();
    expect(state.confirmations).toHaveLength(1);
    expect(state.confirmations[0]).toMatchObject({
      requestId: 'code-1',
      code: '123456',
      items: state.requests[0]?.items,
    });
    expect(screen.queryByRole('checkbox')).not.toBeInTheDocument();
    expect(screen.getByText(fill(t.progress, { signed: 1, total: 1 }))).toBeInTheDocument();
  });

  it('TS-047: чужое личное согласие и компания без полномочия недоступны', async () => {
    const user = userEvent.setup();
    mockConsents(
      makeConsents({
        items: [
          makeConsent(),
          makeConsent({
            kind: 'TURNOVER',
            subjectInn: '7707083893',
            subjectName: 'ООО «Ромашка»',
            subjectType: 'COMPANY',
            canSign: false,
          }),
          makeConsent({
            subjectInn: '540812345679',
            subjectName: 'Другой поручитель',
            canSign: false,
          }),
        ],
      }),
    );
    renderApp('/applications/app-1/edit/4');
    await screen.findByRole('heading', { name: t.heading });
    const boxes = screen.getAllByRole('checkbox');
    expect(boxes[0]).toBeEnabled();
    expect(boxes[1]).toBeDisabled();
    expect(boxes[2]).toBeDisabled();
    await user.click(boxes[1]!);
    expect(boxes[1]).not.toBeChecked();
    expect(screen.getByText(/Ждём подписи:.*Другой поручитель/)).toBeInTheDocument();
  });

  it('подписанное неизменно; прогресс по людям и правила приняты один раз', async () => {
    mockConsents(
      makeConsents({
        pepRules: { ...makeConsents().pepRules, accepted: true },
        items: [
          makeConsent({
            status: 'SIGNED',
            signedAt: '2026-10-22T08:00:00Z',
            validUntil: '2027-04-22',
          }),
          makeConsent({ subjectInn: '540812345679', subjectName: 'Иван Петров' }),
        ],
      }),
    );
    renderApp('/applications/app-1/edit/4');
    expect(await screen.findByText(fill(t.progress, { signed: 1, total: 2 }))).toBeInTheDocument();
    expect(screen.getAllByRole('checkbox')).toHaveLength(1);
    expect(screen.getByText(t.pepAccepted)).toBeInTheDocument();
    expect(screen.getByText(/Действует до/)).toBeInTheDocument();
  });

  it('три неверных кода блокируют пакет, новый код восстанавливает ввод', async () => {
    const user = userEvent.setup();
    const state = mockConsents();
    let failures = 0;
    server.use(
      http.post('*/api/applications/app-1/consents/sign', () => {
        failures += 1;
        return problemResponse({
          status: 422,
          code: failures === 3 ? 'CODE_ATTEMPTS_EXCEEDED' : 'CODE_INVALID',
        });
      }),
    );
    renderApp('/applications/app-1/edit/4');
    await start(user);
    for (let i = 0; i < 3; i += 1) {
      await user.type(screen.getByLabelText(new RegExp(t.codeLabel)), '000000');
      await user.click(screen.getByRole('button', { name: t.sign }));
      if (i < 2) await screen.findByText(fill(t.wrongCode, { attempts: 2 - i }));
    }
    expect(await screen.findByText(t.blocked)).toBeInTheDocument();
    expect(screen.getByLabelText(new RegExp(t.codeLabel))).toBeDisabled();
    expect(screen.queryByRole('button', { name: t.sign })).not.toBeInTheDocument();
    await user.click(screen.getByRole('button', { name: t.newCode }));
    await waitFor(() => expect(screen.getByLabelText(new RegExp(t.codeLabel))).toBeEnabled());
    expect(state.requests).toHaveLength(2);
    expect(state.requests[1]?.items).toEqual(state.requests[0]?.items);
    expect(screen.getByLabelText(new RegExp(t.codeLabel))).toHaveValue('');
  });

  it('истёкший код и серверная блокировка понятны, вне демо код не показан', async () => {
    const user = userEvent.setup();
    mockConsents();
    server.use(
      http.post('*/api/applications/app-1/consents', async ({ request }) =>
        Response.json({
          requestId: 'expired',
          expiresInSeconds: 0,
          demoCode: null,
          items: ((await request.json()) as SignRequest).items,
        }),
      ),
    );
    renderApp('/applications/app-1/edit/4');
    await start(user);
    expect(screen.getByText(t.expiredCode)).toBeInTheDocument();
    expect(screen.getByLabelText(new RegExp(t.codeLabel))).toBeDisabled();
    expect(screen.queryByTestId('consent-demo-code')).not.toBeInTheDocument();
  });

  it('можно изменить пакет; старый код не подтверждает новый состав', async () => {
    const user = userEvent.setup();
    const state = mockConsents();
    renderApp('/applications/app-1/edit/4');
    await start(user);
    await user.click(screen.getByRole('button', { name: t.changeBundle }));
    await user.click(screen.getAllByRole('checkbox')[0]!);
    await user.click(screen.getByRole('button', { name: t.requestCode }));
    await screen.findByLabelText(new RegExp(t.codeLabel));
    expect(state.requests[1]?.items).toHaveLength(2);
    await user.type(screen.getByLabelText(new RegExp(t.codeLabel)), '123456');
    await user.click(screen.getByRole('button', { name: t.sign }));
    await waitFor(() => expect(state.confirmations).toHaveLength(1));
    expect(state.confirmations[0]?.requestId).toBe('code-2');
    expect(state.confirmations[0]?.items).toHaveLength(2);
  });

  it('недоступный сервер можно перечитать, подпись без данных недоступна', async () => {
    mockConsents();
    server.use(
      http.get('*/api/applications/app-1/consents', () =>
        problemResponse({ status: 503, code: 'SERVICE_UNAVAILABLE' }),
      ),
    );
    renderApp('/applications/app-1/edit/4');
    expect(await screen.findByText(errorTexts.SERVICE_UNAVAILABLE.text)).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: t.requestCode })).not.toBeInTheDocument();
    expect(
      screen.getByRole('button', { name: errorTexts.SERVICE_UNAVAILABLE.action }),
    ).toBeEnabled();
  });

  it('TS-056: нельзя отправить заявку до всех обязательных согласий', async () => {
    mockConsents();
    renderApp('/applications/app-1/edit/5');
    expect(await screen.findByText(t.incomplete)).toBeInTheDocument();
    expect(screen.getByRole('button', { name: applicationForm.review.submit })).toBeDisabled();
    expect(screen.getByRole('link', { name: applicationForm.review.toConsents })).toHaveAttribute(
      'href',
      '/applications/app-1/edit/4',
    );
  });

  it('просроченное согласие требует повторной подписи', async () => {
    mockConsents(makeConsents({ items: [makeConsent({ status: 'EXPIRED' })] }));
    renderApp('/applications/app-1/edit/4');
    expect(await screen.findByText(t.expired)).toBeInTheDocument();
    expect(screen.getAllByRole('checkbox')[0]).toBeEnabled();
  });

  it('участник без права подписи видит пояснение вместо формы кода', async () => {
    mockConsents(makeConsents({ items: [makeConsent({ canSign: false })] }));
    renderApp('/applications/app-1/edit/4');
    expect(await screen.findByText(t.noAvailable)).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: t.requestCode })).not.toBeInTheDocument();
  });
});
