import { PlaceholderPage } from '@/components/PlaceholderPage';
import { placeholders } from '@/texts';

/** Главная клиента: задачи, заявки, кредиты, предодобрение (60-03). Экран делает отдельная задача */
export function HomePage() {
  return <PlaceholderPage content={placeholders.home} />;
}
