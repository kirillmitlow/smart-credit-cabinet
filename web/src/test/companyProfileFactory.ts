import type { CompanyProfile, ProfileField } from '@/api/generated/model';

export function makeProfileField(overrides: Partial<ProfileField> = {}): ProfileField {
  return {
    value: null,
    source: 'registry',
    retrievedAt: '2026-10-22T09:00:00Z',
    confirmed: true,
    ...overrides,
  };
}

export function makeCompanyProfile(overrides: Partial<CompanyProfile> = {}): CompanyProfile {
  return {
    companyId: 'company-1',
    inn: '7707083893',
    form: 'LEGAL',
    eligibility: 'ELIGIBLE',
    fetchedAt: '2026-10-22T09:00:00Z',
    relatedCompanies: [],
    fields: {
      inn: makeProfileField({ value: '7707083893' }),
      name: makeProfileField({ value: 'ООО «Ромашка»' }),
      address: makeProfileField({ value: 'Новосибирск, улица Ленина, 1' }),
      status: makeProfileField({ value: 'ACTIVE' }),
      taxRegime: makeProfileField({ value: 'USN_INCOME', source: 'tax' }),
      isBankCustomer: makeProfileField({ value: false, source: 'bank_core' }),
    },
    ...overrides,
  };
}
