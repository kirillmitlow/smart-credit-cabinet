import type { BankApplicationCard, BankDecision } from '@/api/generated/model';
import decisionJson from './fixtures/bankDecision.json';

/** Числа, причины и факторы экспортированы из ядра и банковской проекции СтанкоПрома. */
export function makeBankDecision(overrides: Partial<BankDecision> = {}): BankDecision {
  return { ...(structuredClone(decisionJson) as BankDecision), ...overrides };
}

export function makeBankCard(overrides: Partial<BankApplicationCard> = {}): BankApplicationCard {
  const decision = makeBankDecision();
  return {
    id: 'bank-app',
    number: 'АЗ-2026-000001',
    status: 'MANUAL_REVIEW',
    version: 3,
    stale: false,
    currentVersionId: 'version-1',
    productCode: 'INVESTMENT',
    amountRub: 15_000_000,
    termMonths: 60,
    purposeCode: 'EQUIPMENT',
    draft: {},
    company: {
      id: 'company-1',
      name: 'ООО «СтанкоПром»',
      inn: '0012345678',
      isBankCustomer: false,
      registeredOn: '2017-03-14',
      status: 'ACTIVE',
      okved: '25.62',
    },
    submittedBy: { id: 'accountant-1', name: 'Белова Мария', companyRole: 'ACCOUNTANT' },
    submittedAt: '2026-10-21T10:00:00Z',
    decision,
    engineDecisionId: decision.id,
    engineRecommendation: decision.recommendation,
    decisions: [decision],
    sourceSnapshots: [
      {
        id: decision.snapshotIds[0] ?? 'snapshot-1',
        runId: 'run-1',
        system: 'registry',
        resource: 'registry:company',
        subjectInn: '0012345678',
        status: 'OK',
        dataActualAt: '2026-10-18',
        retrievedAt: '2026-10-21T10:00:00Z',
        requestId: 'req-registry',
        payloadHash: 'a'.repeat(64),
        payload: { name: 'СтанкоПром', status: 'ACTIVE' },
        usedByCurrentDecision: true,
      },
    ],
    history: [
      {
        id: 1,
        at: '2026-10-21T10:00:00Z',
        kind: 'TRANSITION',
        fromStatus: 'CHECKING',
        toStatus: 'MANUAL_REVIEW',
        stepCode: null,
        actorType: 'SYSTEM',
        actorId: null,
        actorName: null,
        reasonCode: 'COLLATERAL_REVIEW',
        payload: {},
        requestId: 'req-submit',
      },
    ],
    documents: null,
    ...overrides,
  };
}
