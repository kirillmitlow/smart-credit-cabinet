import { demo as t } from '@/texts/demo';
export function outcome(value?: string | null) {
  return value ? (t.outcomes[value as keyof typeof t.outcomes] ?? value) : t.unknown;
}
