import type { CompanyChoice } from '@/api/generated/model';
import { useSession } from './session';

export interface ActiveCompany {
  /** Выбранная компания пользователя: активная из сессии, а при единственной — она сама */
  choice: CompanyChoice | null;
  /** Роль пользователя в ней (`DIRECTOR`, `ACCOUNTANT`, `GUARANTOR`) */
  role: string | null;
  /** Можно ли подавать заявку от её имени (компания действует) */
  canApply: boolean;
}

/** Активная компания клиента из `GET /me`; нужна экранам, где от компании зависят кнопки */
export function useActiveCompany(): ActiveCompany {
  const me = useSession('client').data;
  const companies = me?.companies ?? [];
  const choice =
    companies.find((item) => item.company.id === me?.activeCompanyId) ??
    (companies.length === 1 ? (companies[0] ?? null) : null);
  return {
    choice,
    role: choice?.role ?? null,
    canApply: choice?.company.canApply ?? true,
  };
}
