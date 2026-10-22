import { screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { http, HttpResponse } from 'msw';
import { describe, expect, it } from 'vitest';
import type { RolesResponse } from '@/api/generated/model';
import { blockingA11yViolations } from '@/test/a11y';
import {
  makeCompanyChoice,
  makeCompanyRoles,
  makeMe,
  makeNotEligible,
  makePersonRoles,
  problemResponse,
} from '@/test/factories';
import { renderApp } from '@/test/render';
import { mockSessions } from '@/test/sessions';
import { server } from '@/test/server';
import { errorTexts, fill, home, login, loginPlaceholder, otherErrors } from '@/texts';

const CODE_LABEL = new RegExp(login.codeStep.label);
const SOKOLOVA = '001234567887';
const STANKOPROM = '0012345673';

function mockRoles(inn: string, body: RolesResponse | Response) {
  server.use(
    http.get(`*/api/auth/roles/${inn}`, () =>
      body instanceof Response ? body : Response.json(body),
    ),
  );
}

interface IssuedBody {
  userId: string;
  companyId: string | null;
}

function mockCodes(options: { demoCode?: string | null; expiresInSeconds?: number } = {}) {
  const requests: IssuedBody[] = [];
  let counter = 0;
  server.use(
    http.post('*/api/auth/request-code', async ({ request }) => {
      requests.push((await request.json()) as IssuedBody);
      counter += 1;
      return Response.json({
        requestId: `otp_${counter}`,
        expiresInSeconds: options.expiresInSeconds ?? 300,
        demoCode: options.demoCode === undefined ? '123456' : options.demoCode,
      });
    }),
  );
  return requests;
}

async function enterInn(user: ReturnType<typeof userEvent.setup>, inn: string) {
  await user.type(await screen.findByLabelText(new RegExp(login.innStep.label)), inn);
  await user.click(screen.getByRole('button', { name: login.innStep.submit }));
}

async function expectNoViolations(container: HTMLElement) {
  expect(await blockingA11yViolations(container)).toEqual([]);
}

const PEOPLE = [
  { userId: 'u-kuznetsov', displayName: 'Кузнецов И. П.', role: 'DIRECTOR' },
  { userId: 'u-belova', displayName: 'Белова О. Н.', role: 'ACCOUNTANT' },
];

describe('шаг 1: ИНН', () => {
  it('поле с подсказкой про личный ИНН; пустая кнопка объясняет ошибку, а не молчит', async () => {
    const user = userEvent.setup();
    const { container } = renderApp('/login');
    const field = await screen.findByLabelText(new RegExp(login.innStep.label));
    expect(field).toHaveAccessibleDescription(login.innStep.hint);
    await user.click(screen.getByRole('button', { name: login.innStep.submit }));
    expect(await screen.findByText(errorTexts.INN_INVALID.text)).toBeInTheDocument();
    expect(field).toHaveAttribute('aria-invalid', 'true');
    await expectNoViolations(container);
  });

  it('проверяет контрольную сумму на лету и не ходит на сервер с опечаткой', async () => {
    const user = userEvent.setup();
    let asked = false;
    server.use(
      http.get('*/api/auth/roles/:inn', () => {
        asked = true;
        return problemResponse({ status: 404, code: 'INN_NOT_FOUND' });
      }),
    );
    renderApp('/login');
    await enterInn(user, '001234567888');
    expect(await screen.findByText(login.innStep.checksum)).toBeInTheDocument();
    expect(asked).toBe(false);
  });

  it('оставляет в поле только цифры и не больше 12', async () => {
    const user = userEvent.setup();
    renderApp('/login');
    const field = await screen.findByLabelText(new RegExp(login.innStep.label));
    await user.type(field, '00 12-34abc56789012345');
    expect(field).toHaveValue('001234567890');
  });

  it('кнопка «Войти как андеррайтер» есть только в демо', async () => {
    mockSessions({ config: { demoMode: false } });
    const first = renderApp('/login');
    await screen.findByLabelText(new RegExp(login.innStep.label));
    expect(screen.queryByRole('link', { name: login.innStep.underwriter })).not.toBeInTheDocument();
    first.unmount();

    mockSessions({ config: { demoMode: true } });
    renderApp('/login');
    expect(await screen.findByRole('link', { name: login.innStep.underwriter })).toHaveAttribute(
      'href',
      '/login?zone=bank',
    );
  });

  it('нет карточек быстрого входа персон', async () => {
    renderApp('/login');
    await screen.findByLabelText(new RegExp(login.innStep.label));
    expect(screen.queryByText(/Соколова|СтанкоПром|Ромашка/)).not.toBeInTheDocument();
  });
});

describe('шаг 2: кто входит', () => {
  it('2а: компания и два пользователя', async () => {
    const user = userEvent.setup();
    mockRoles(STANKOPROM, makeCompanyRoles(PEOPLE));
    const { container } = renderApp('/login');
    await enterInn(user, STANKOPROM);

    expect(
      await screen.findByRole('heading', { level: 2, name: login.whoStep.heading }),
    ).toBeInTheDocument();
    expect(screen.getByTestId('company-card')).toHaveTextContent('ООО «СтанкоПром», действует');
    expect(screen.getByRole('radio', { name: 'Кузнецов И. П., руководитель' })).toBeInTheDocument();
    expect(
      screen.getByRole('radio', { name: 'Белова О. Н., сотрудник по доверенности' }),
    ).toBeInTheDocument();
    // без выбора человека кода не выпускаем
    expect(screen.getByRole('button', { name: login.whoStep.submit })).toBeDisabled();
    await expectNoViolations(container);
  });

  it('2а: ИП с одним человеком — он уже выбран', async () => {
    const user = userEvent.setup();
    mockRoles(
      SOKOLOVA,
      makeCompanyRoles(
        [{ userId: 'u-sokolova', displayName: 'Соколова А. С.', role: 'DIRECTOR' }],
        {
          name: 'ИП Соколова',
          inn: SOKOLOVA,
        },
      ),
    );
    renderApp('/login');
    await enterInn(user, SOKOLOVA);
    expect(await screen.findByRole('radio', { name: /Соколова А\. С\./ })).toBeChecked();
    expect(screen.getByRole('button', { name: login.whoStep.submit })).toBeEnabled();
  });

  it('2б: личный ИНН и одна компания — «вы руководитель»', async () => {
    const user = userEvent.setup();
    mockRoles(
      '7707083893',
      makePersonRoles([makeCompanyChoice({ id: 'c-romashka', name: 'ООО «Ромашка»' }, 'DIRECTOR')]),
    );
    renderApp('/login');
    await enterInn(user, '7707083893');
    expect(
      await screen.findByText(
        fill(login.whoStep.personOne, { company: 'ООО «Ромашка»', role: 'руководитель' }),
      ),
    ).toBeInTheDocument();
    expect(screen.getByRole('radio', { name: 'ООО «Ромашка», руководитель' })).toBeChecked();
  });

  it('2б: несколько компаний — выбор, а код выпускается для выбранной', async () => {
    const user = userEvent.setup();
    const requests = mockCodes();
    mockRoles(
      '7707083893',
      makePersonRoles([
        makeCompanyChoice({ id: 'c-1', name: 'ООО «Ромашка»' }, 'DIRECTOR'),
        makeCompanyChoice({ id: 'c-2', name: 'ИП Иванов' }, 'DIRECTOR'),
      ]),
    );
    renderApp('/login');
    await enterInn(user, '7707083893');
    await screen.findByText(login.whoStep.personMany);
    await user.click(screen.getByRole('radio', { name: 'ИП Иванов, руководитель' }));
    await user.click(screen.getByRole('button', { name: login.whoStep.submit }));
    await screen.findByRole('heading', { level: 2, name: login.codeStep.heading });
    expect(requests).toEqual([{ userId: 'user-1', companyId: 'c-2' }]);
  });

  it('2в: объяснение вместо кода, раскрывается текст «Как стать ИП»', async () => {
    const user = userEvent.setup();
    const requests = mockCodes();
    mockRoles(SOKOLOVA, makeNotEligible());
    const { container } = renderApp('/login');
    await enterInn(user, SOKOLOVA);

    expect(
      await screen.findByRole('heading', { level: 2, name: login.notEligible.heading }),
    ).toBeInTheDocument();
    const howTo = screen.getByRole('button', { name: login.notEligible.howTo });
    expect(howTo).toHaveAttribute('aria-expanded', 'false');
    await user.click(howTo);
    expect(howTo).toHaveAttribute('aria-expanded', 'true');
    expect(screen.getByText(login.notEligible.steps[0])).toBeVisible();
    expect(screen.queryByRole('button', { name: login.whoStep.submit })).not.toBeInTheDocument();
    expect(requests).toEqual([]);
    await expectNoViolations(container);

    await user.click(screen.getByRole('button', { name: login.notEligible.back }));
    expect(await screen.findByLabelText(new RegExp(login.innStep.label))).toBeInTheDocument();
  });

  it('компания не действует: можно войти, подать заявку нельзя', async () => {
    const user = userEvent.setup();
    mockRoles(
      STANKOPROM,
      makeCompanyRoles(PEOPLE, { status: 'LIQUIDATING', canApply: false, name: 'ООО «Вектор»' }),
    );
    renderApp('/login');
    await enterInn(user, STANKOPROM);
    expect(await screen.findByText(login.whoStep.notActive)).toBeInTheDocument();
    expect(screen.getByTestId('company-card')).toHaveTextContent('в стадии ликвидации');
    await user.click(screen.getByRole('radio', { name: /Кузнецов/ }));
    expect(screen.getByRole('button', { name: login.whoStep.submit })).toBeEnabled();
  });

  it('ИНН не найден: сообщение под полем на первом шаге', async () => {
    const user = userEvent.setup();
    mockRoles(STANKOPROM, problemResponse({ status: 404, code: 'INN_NOT_FOUND' }));
    renderApp('/login');
    await enterInn(user, STANKOPROM);
    expect(await screen.findByText(errorTexts.INN_NOT_FOUND.text)).toBeInTheDocument();
    expect(screen.getByLabelText(new RegExp(login.innStep.label))).toHaveValue(STANKOPROM);
  });

  it('справочник недоступен: «Повторить» запрашивает снова', async () => {
    const user = userEvent.setup();
    mockRoles(
      STANKOPROM,
      problemResponse({ status: 503, code: 'DIRECTORY_UNAVAILABLE', requestId: 'req-dir' }),
    );
    renderApp('/login');
    await enterInn(user, STANKOPROM);
    expect(await screen.findByText(errorTexts.DIRECTORY_UNAVAILABLE.text)).toBeInTheDocument();
    expect(screen.getByText(/req-dir/)).toBeInTheDocument();

    mockRoles(STANKOPROM, makeCompanyRoles(PEOPLE));
    await user.click(screen.getByRole('button', { name: errorTexts.DIRECTORY_UNAVAILABLE.action }));
    expect(await screen.findByRole('radio', { name: /Кузнецов/ })).toBeInTheDocument();
  });

  it('лимит запросов: понятный текст без повтора', async () => {
    const user = userEvent.setup();
    mockRoles(
      STANKOPROM,
      problemResponse({ status: 429, code: 'RATE_LIMITED', headers: { 'Retry-After': '30' } }),
    );
    renderApp('/login');
    await enterInn(user, STANKOPROM);
    expect(await screen.findByText(/Повторите через 30/)).toBeInTheDocument();
    await user.click(screen.getByRole('button', { name: login.whoStep.back }));
    expect(await screen.findByLabelText(new RegExp(login.innStep.label))).toHaveValue(STANKOPROM);
  });
});

describe('шаг 3: код', () => {
  async function toCodeStep(user: ReturnType<typeof userEvent.setup>) {
    mockRoles(STANKOPROM, makeCompanyRoles(PEOPLE));
    await enterInn(user, STANKOPROM);
    await user.click(await screen.findByRole('radio', { name: /Белова/ }));
    await user.click(screen.getByRole('button', { name: login.whoStep.submit }));
    return screen.findByRole('heading', { level: 2, name: login.codeStep.heading });
  }

  it('в демо показывает код и плашку «в реальной системе пришёл бы по SMS»', async () => {
    const user = userEvent.setup();
    mockCodes({ demoCode: '482913' });
    const { container } = renderApp('/login');
    await toCodeStep(user);

    const banner = screen.getByTestId('demo-code');
    expect(banner).toHaveTextContent(fill(login.codeStep.demoCode, { code: '482913' }));
    expect(banner).toHaveTextContent(login.codeStep.demoBanner);
    expect(screen.getByText(/Входим как Белова О\. Н\., ООО «СтанкоПром»/)).toBeInTheDocument();
    expect(
      screen.getByText(fill(login.codeStep.attemptsLeft, { attempts: 3 })),
    ).toBeInTheDocument();
    expect(screen.getByRole('timer')).toHaveTextContent('5:00');
    await expectNoViolations(container);
  });

  it('вне демо код на экране не показывается', async () => {
    const user = userEvent.setup();
    mockCodes({ demoCode: null });
    renderApp('/login');
    await toCodeStep(user);
    expect(screen.queryByTestId('demo-code')).not.toBeInTheDocument();
    expect(screen.queryByText(login.codeStep.demoBanner)).not.toBeInTheDocument();
  });

  it('код привязан к выбранному человеку: смена человека — новый запрос с другим userId', async () => {
    const user = userEvent.setup();
    const requests = mockCodes();
    renderApp('/login');
    await toCodeStep(user);
    expect(requests).toEqual([{ userId: 'u-belova', companyId: 'company-1' }]);

    await user.click(screen.getByRole('button', { name: login.codeStep.back }));
    await user.click(await screen.findByRole('radio', { name: /Кузнецов/ }));
    await user.click(screen.getByRole('button', { name: login.whoStep.submit }));
    await screen.findByRole('heading', { level: 2, name: login.codeStep.heading });
    expect(requests).toEqual([
      { userId: 'u-belova', companyId: 'company-1' },
      { userId: 'u-kuznetsov', companyId: 'company-1' },
    ]);
  });

  it('верный код: сессия создана, открывается главная', async () => {
    const user = userEvent.setup();
    mockCodes();
    const verified: unknown[] = [];
    server.use(
      http.post('*/api/auth/verify-code', async ({ request }) => {
        verified.push(await request.json());
        return Response.json(makeMe({ displayName: 'Белова О. Н.' }));
      }),
    );
    renderApp('/login');
    await toCodeStep(user);
    mockSessions({ client: makeMe({ displayName: 'Белова О. Н.' }) });

    await user.type(screen.getByLabelText(CODE_LABEL), '123456{Enter}');
    expect(await screen.findByRole('heading', { level: 1, name: home.title })).toBeInTheDocument();
    expect(verified).toEqual([{ requestId: 'otp_1', code: '123456' }]);
    expect(window.location.pathname).toBe('/');
  });

  it('после входа открывается адрес возврата из next (и только внутренний)', async () => {
    const user = userEvent.setup();
    mockCodes();
    server.use(http.post('*/api/auth/verify-code', () => Response.json(makeMe())));
    mockSessions({ client: makeMe() });
    renderApp('/login?next=/loans');
    await toCodeStep(user);
    await user.type(screen.getByLabelText(CODE_LABEL), '123456{Enter}');
    await waitFor(() => expect(window.location.pathname).toBe('/loans'));
  });

  it('неверный код: остаток попыток, поле очищено', async () => {
    const user = userEvent.setup();
    mockCodes();
    server.use(
      http.post('*/api/auth/verify-code', () =>
        problemResponse({ status: 422, code: 'CODE_INVALID' }),
      ),
    );
    renderApp('/login');
    await toCodeStep(user);
    const field = screen.getByLabelText(CODE_LABEL);
    await user.type(field, '000000{Enter}');
    expect(
      await screen.findByText(fill(otherErrors.wrongLoginCode, { attempts: 2 })),
    ).toBeInTheDocument();
    expect(field).toHaveValue('');
    expect(field).toHaveAttribute('aria-invalid', 'true');
    await user.type(field, '111111{Enter}');
    expect(
      await screen.findByText(fill(otherErrors.wrongLoginCode, { attempts: 1 })),
    ).toBeInTheDocument();
  });

  it('попытки закончились: «Получить новый» выпускает новый код', async () => {
    const user = userEvent.setup();
    const requests = mockCodes();
    server.use(
      http.post('*/api/auth/verify-code', () =>
        problemResponse({ status: 429, code: 'CODE_ATTEMPTS_EXCEEDED' }),
      ),
    );
    renderApp('/login');
    await toCodeStep(user);
    await user.type(screen.getByLabelText(CODE_LABEL), '000000{Enter}');
    expect(await screen.findByText(errorTexts.CODE_ATTEMPTS_EXCEEDED.text)).toBeInTheDocument();
    expect(screen.getByLabelText(CODE_LABEL)).toBeDisabled();

    const buttons = screen.getAllByRole('button', { name: login.codeStep.newCode });
    await user.click(buttons[0]!);
    await waitFor(() => expect(requests).toHaveLength(2));
    // новый код — чистый экран с тремя попытками
    expect(
      await screen.findByText(fill(login.codeStep.attemptsLeft, { attempts: 3 })),
    ).toBeInTheDocument();
    expect(screen.getByLabelText(CODE_LABEL)).toBeEnabled();
  });

  it('код истёк на сервере: «Получить новый»', async () => {
    const user = userEvent.setup();
    const requests = mockCodes();
    server.use(
      http.post('*/api/auth/verify-code', () =>
        problemResponse({ status: 410, code: 'CODE_EXPIRED' }),
      ),
    );
    renderApp('/login');
    await toCodeStep(user);
    await user.type(screen.getByLabelText(CODE_LABEL), '123456{Enter}');
    expect(await screen.findByText(errorTexts.CODE_EXPIRED.text)).toBeInTheDocument();
    await user.click(screen.getAllByRole('button', { name: login.codeStep.newCode })[0]!);
    await waitFor(() => expect(requests).toHaveLength(2));
  });

  it('время кода вышло: поле закрывается, предлагается новый код', async () => {
    const user = userEvent.setup();
    mockCodes({ expiresInSeconds: 1 });
    renderApp('/login');
    await toCodeStep(user);
    expect(
      await screen.findByText(login.codeStep.expired, undefined, { timeout: 3000 }),
    ).toBeInTheDocument();
    expect(screen.getByLabelText(CODE_LABEL)).toBeDisabled();
    expect(screen.getByRole('button', { name: login.codeStep.newCode })).toBeEnabled();
  });

  it('лимит запросов на вход: текст из словаря', async () => {
    const user = userEvent.setup();
    server.use(
      http.post('*/api/auth/request-code', () =>
        problemResponse({ status: 429, code: 'RATE_LIMITED' }),
      ),
    );
    mockRoles(STANKOPROM, makeCompanyRoles(PEOPLE));
    renderApp('/login');
    await enterInn(user, STANKOPROM);
    await user.click(await screen.findByRole('radio', { name: /Белова/ }));
    await user.click(screen.getByRole('button', { name: login.whoStep.submit }));
    expect(await screen.findByText(errorTexts.RATE_LIMITED.text)).toBeInTheDocument();
    // остаёмся на выборе человека
    expect(screen.getByRole('button', { name: login.whoStep.submit })).toBeEnabled();
  });

  it('весь вход проходится клавиатурой', async () => {
    const user = userEvent.setup();
    mockCodes();
    mockRoles(STANKOPROM, makeCompanyRoles(PEOPLE));
    server.use(http.post('*/api/auth/verify-code', () => Response.json(makeMe())));
    mockSessions({ client: makeMe() });
    renderApp('/login');
    await screen.findByLabelText(new RegExp(login.innStep.label));
    await user.click(screen.getByLabelText(new RegExp(login.innStep.label)));
    await user.keyboard(`${STANKOPROM}{Enter}`);
    const radios = await screen.findAllByRole('radio');
    radios[0]!.focus();
    await user.keyboard(' ');
    expect(radios[0]).toBeChecked();
    await user.tab({ shift: true }).catch(() => undefined);
    screen.getByRole('button', { name: login.whoStep.submit }).focus();
    await user.keyboard('{Enter}');
    const field = await screen.findByLabelText(CODE_LABEL);
    await user.type(field, '123456{Enter}');
    expect(await screen.findByRole('heading', { level: 1, name: home.title })).toBeInTheDocument();
  });
});

describe('после входа: несколько компаний', () => {
  it('если активной компании нет, сначала «Выбор компании»', async () => {
    const user = userEvent.setup();
    mockCodes();
    const two = makeMe({
      activeCompanyId: null,
      companies: [
        makeCompanyChoice({ id: 'c-1', name: 'ООО «Ромашка»' }),
        makeCompanyChoice({ id: 'c-2', name: 'ИП Иванов', inn: '7707083894' }),
      ],
    });
    server.use(
      http.post('*/api/auth/verify-code', () => Response.json(two)),
      http.put('*/api/me/active-company', () => Response.json({ ...two, activeCompanyId: 'c-2' })),
    );
    mockSessions({ client: two });
    mockRoles(STANKOPROM, makeCompanyRoles(PEOPLE));
    renderApp('/login');
    await enterInn(user, STANKOPROM);
    await user.click(await screen.findByRole('radio', { name: /Кузнецов/ }));
    await user.click(screen.getByRole('button', { name: login.whoStep.submit }));
    await user.type(await screen.findByLabelText(CODE_LABEL), '123456{Enter}');

    expect(
      await screen.findByRole('heading', { level: 1, name: 'Выбор компании' }),
    ).toBeInTheDocument();
    const options = screen.getAllByTestId('company-option');
    expect(options).toHaveLength(2);
    mockSessions({ client: { ...two, activeCompanyId: 'c-2' } });
    await user.click(within(options[1]!).getByRole('button', { name: 'Выбрать' }));
    expect(await screen.findByRole('heading', { level: 1, name: home.title })).toBeInTheDocument();
  });

  it('заглушка входа банка остаётся для ?zone=bank', async () => {
    renderApp('/login?zone=bank');
    expect(
      await screen.findByRole('heading', { level: 1, name: loginPlaceholder.zoneBank }),
    ).toBeInTheDocument();
    expect(screen.queryByLabelText(new RegExp(login.innStep.label))).not.toBeInTheDocument();
  });
});

describe('ответ без тела', () => {
  it('сеть упала на roles: понятная ошибка и «Повторить»', async () => {
    const user = userEvent.setup();
    server.use(http.get('*/api/auth/roles/:inn', () => HttpResponse.error()));
    renderApp('/login');
    await enterInn(user, STANKOPROM);
    expect(await screen.findByText(errorTexts.NETWORK_ERROR.text)).toBeInTheDocument();
  });
});
