import { PlaceholderPage } from '@/components/PlaceholderPage';
import { placeholders } from '@/texts';

/** Очередь заявок банка (60-04). Экран делает отдельная задача */
export function BankQueuePage() {
  return <PlaceholderPage content={placeholders.bankQueue} />;
}

/** Карточка заявки для специалиста банка (60-04) */
export function BankApplicationPage() {
  return <PlaceholderPage content={placeholders.bankApplication} />;
}
