import { HttpResponse } from 'msw';
import type { CompanyBrief, CompanyChoice, PublicConfig } from '@/api/generated/model';
import type { Me } from '@/features/auth/session';

/** Фабрики данных для тестов: значения по умолчанию валидны, тест переопределяет только важное */

export function makeCompanyChoice(
  overrides: Partial<CompanyBrief> = {},
  role = 'DIRECTOR',
): CompanyChoice {
  return {
    company: {
      id: 'company-1',
      inn: '7707083893',
      name: 'ООО «Ромашка»',
      status: 'ACTIVE',
      canApply: true,
      ...overrides,
    },
    role,
  };
}

export function makeMe(overrides: Partial<Me> = {}): Me {
  return {
    userId: 'user-1',
    displayName: 'Анна Соколова',
    role: 'CLIENT',
    activeCompanyId: 'company-1',
    companies: [makeCompanyChoice()],
    ...overrides,
  };
}

export function makeBankMe(role = 'UNDERWRITER', overrides: Partial<Me> = {}): Me {
  return makeMe({
    userId: 'bank-user-1',
    displayName: 'Ольга Петрова',
    role,
    companies: [],
    activeCompanyId: null,
    ...overrides,
  });
}

export function makePublicConfig(overrides: Partial<PublicConfig> = {}): PublicConfig {
  return {
    demoMode: true,
    productName: 'Умный кредитный кабинет',
    version: '0.1.0',
    nluAvailable: false,
    ...overrides,
  };
}

export interface ProblemInit {
  status: number;
  code: string;
  title?: string;
  detail?: string;
  requestId?: string;
  errors?: { field: string; code?: string; message?: string }[];
  headers?: Record<string, string>;
}

/** Ответ `application/problem+json` в форме, которую отдаёт api (50-07) */
export function problemResponse(init: ProblemInit): Response {
  const { status, code, title, detail, requestId, errors, headers } = init;
  return HttpResponse.json(
    {
      type: `https://errors.example/${code.toLowerCase()}`,
      title: title ?? code,
      status,
      code,
      detail: detail ?? 'Служебное описание для разработчика',
      requestId: requestId ?? 'req-test-1',
      ...(errors ? { errors } : {}),
    },
    {
      status,
      headers: { 'Content-Type': 'application/problem+json', ...headers },
    },
  );
}
