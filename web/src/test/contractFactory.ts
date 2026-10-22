import type { ConsentsOut, ContractOut, OfferOut } from '@/api/generated/model';

export const testOffer = (over: Partial<OfferOut> = {}): OfferOut => ({
  id: 'offer-1',
  applicationId: 'app-1',
  kind: 'AS_REQUESTED',
  status: 'OPEN',
  variantsStatus: 'READY',
  expiresAt: '2027-01-01T12:00:00Z',
  acceptedVariantId: null,
  contractId: null,
  variants: [],
  ...over,
});

export const testContract = (over: Partial<ContractOut> = {}): ContractOut => ({
  id: 'contract-1',
  applicationId: 'app-1',
  applicationStatus: 'OFFER_ACCEPTED',
  contractUid: 'test-uid',
  number: 'КД-2026-000001',
  status: 'READY',
  contentHash: 'hash',
  templateVersion: 'credit-agreement-v1',
  createdAt: '2026-10-22T09:00:00Z',
  signedAt: null,
  productCode: 'EXPRESS',
  amountRub: 500_000,
  termMonths: 12,
  ratePercent: 21.5,
  paymentRub: 46_677,
  signers: [{ role: 'DIRECTOR', name: 'Анна Соколова', signed: false, signedAt: null }],
  progress: { signed: 0, required: 1 },
  canSign: true,
  canPassToDirector: false,
  ...over,
});

export const testConsents = (accepted = true): ConsentsOut => ({
  applicationId: 'app-1',
  pepRules: { version: 'pep-rules-v1', textHash: 'hash', text: 'Правила подписи', accepted },
  items: [],
  allSigned: true,
});
