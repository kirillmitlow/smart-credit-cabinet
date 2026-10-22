import { login } from '@/texts';

/** Статус компании словами клиента; незнакомый статус и «нет данных» не показываем кодом */
export function companyStatusText(status: string | null | undefined): string {
  const labels: Record<string, string> = login.companyStatus;
  if (!status) return login.companyStatus.unknown;
  return labels[status] ?? login.companyStatus.unknown;
}

/** Роль человека в компании словами клиента («руководитель», «сотрудник по доверенности») */
export function roleText(role: string): string {
  const labels: Record<string, string> = login.roles;
  return labels[role] ?? login.roles.other;
}
