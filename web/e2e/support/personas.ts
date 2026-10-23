/**
 * Встроенные персоны для входа в e2e. ИНН совпадают с моком сценариев (docs/specs/mocks.md, 10-02);
 * ожидаемые исходы и коды причин берутся из мока и в браузерных тестах не копируются.
 */
export interface Persona {
  code: string;
  inn: string;
  personName?: string;
}

export const personas = {
  sokolova: { code: 'sokolova', inn: '001234567887' },
} as const satisfies Record<string, Persona>;
