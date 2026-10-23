import { test as base, type Page } from '@playwright/test';
import { loginAsClient, loginAsUnderwriter } from '../support/login';
import { resetPersona } from '../support/persona';
import { personas, type Persona } from '../support/personas';

interface Sessions {
  /** Клиент, уже вошедший как персона теста */
  client: Page;
  /** Андеррайтер в отдельном окне (свои cookie, D-085). Вход выполняется при первом обращении */
  bank: () => Promise<Page>;
}

interface Fixtures {
  /** Кем идёт тест; меняется через `test.use({ persona: personas.snabkontrakt })` */
  persona: Persona;
  /** Клиент, вошедший по ИНН персоны через интерфейс, с проверенным чистым состоянием */
  clientPage: Page;
  /** Две независимые сессии: клиент и банк (D-085) */
  sessions: Sessions;
}

export const test = base.extend<Fixtures>({
  persona: [personas.sokolova, { option: true }],

  clientPage: async ({ page, persona }, provide) => {
    await loginAsClient(page, persona.inn, persona.personName);
    await resetPersona(page.request, persona.code);
    await provide(page);
  },

  sessions: async ({ clientPage, browser }, provide) => {
    const bankContext = await browser.newContext();
    let bankPage: Page | undefined;
    await provide({
      client: clientPage,
      bank: async () => {
        if (!bankPage) {
          bankPage = await bankContext.newPage();
          await loginAsUnderwriter(bankPage);
        }
        return bankPage;
      },
    });
    await bankContext.close();
  },
});

export { expect } from '@playwright/test';
