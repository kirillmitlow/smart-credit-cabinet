import { HttpResponse } from 'msw';
import type {
  ApplicationOut,
  CompanyBrief,
  CompanyChoice,
  ConsentsOut,
  ConsentItemOut,
  PublicConfig,
  RolesResponse,
} from '@/api/generated/model';
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

export function makeApplication(overrides: Partial<ApplicationOut> = {}): ApplicationOut {
  return {
    id: 'app-1',
    companyId: 'company-1',
    number: 'АЗ-2026-000001',
    status: 'DRAFT',
    productCode: 'EXPRESS',
    amountRub: 500_000,
    termMonths: 12,
    purposeCode: null,
    draft: {},
    version: 1,
    createdAt: '2026-10-21T09:00:00Z',
    submittedAt: null,
    allowedActions: ['EDIT_DRAFT', 'SUBMIT', 'DELETE_DRAFT'],
    ...overrides,
  };
}

export function makeCompanyRoles(
  people: { userId: string; displayName: string; role: string }[],
  company: Partial<CompanyBrief> = {},
): RolesResponse {
  return {
    kind: 'COMPANY',
    company: {
      id: 'company-1',
      inn: '0012345673',
      name: 'ООО «СтанкоПром»',
      status: 'ACTIVE',
      canApply: true,
      ...company,
    },
    people,
    companies: [],
    reasonCode: null,
  };
}

export function makePersonRoles(
  choices: CompanyChoice[],
  person = { userId: 'user-1', displayName: 'Анна Соколова', role: 'PERSON' },
): RolesResponse {
  return { kind: 'PERSON', company: null, people: [person], companies: choices, reasonCode: null };
}

export function makeNotEligible(): RolesResponse {
  return {
    kind: 'NOT_ELIGIBLE',
    company: null,
    people: [],
    companies: [],
    reasonCode: 'SELF_EMPLOYED',
  };
}

export function makeConsent(overrides: Partial<ConsentItemOut> = {}): ConsentItemOut {
  return {
    kind: 'BKI',
    subjectInn: '540812345678',
    subjectName: 'Анна Соколова',
    subjectType: 'PERSON',
    role: 'IP',
    status: 'PENDING',
    canSign: true,
    textVersion: 'bki-v1',
    textHash: 'hash-v1',
    text: 'Согласие на запрос кредитной истории.',
    signedAt: null,
    validUntil: null,
    consentId: null,
    ...overrides,
  };
}

export function makeConsents(overrides: Partial<ConsentsOut> = {}): ConsentsOut {
  return {
    applicationId: 'app-1',
    pepRules: {
      version: 'pep-v1',
      textHash: 'pep-hash',
      text: 'Правила простой подписи.',
      accepted: false,
    },
    items: [
      makeConsent(),
      makeConsent({ kind: 'TURNOVER', subjectType: 'COMPANY' }),
      makeConsent({ kind: 'PERSONAL_DATA' }),
    ],
    allSigned: false,
    ...overrides,
  };
}
