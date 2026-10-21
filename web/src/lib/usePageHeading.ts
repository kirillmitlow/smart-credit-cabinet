import { useEffect, useRef } from 'react';
import { shell } from '@/texts';

/** Заголовок страницы: вкладка браузера и фокус на заголовке при смене экрана (читает скринридер) */
export function usePageHeading(title: string) {
  const ref = useRef<HTMLHeadingElement>(null);
  useEffect(() => {
    document.title = `${title} — ${shell.productName}`;
    ref.current?.focus({ preventScroll: true });
  }, [title]);
  return ref;
}
