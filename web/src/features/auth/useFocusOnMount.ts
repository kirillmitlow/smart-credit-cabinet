import { useEffect, useRef } from 'react';

/** Заголовок шага получает фокус при появлении: скринридер читает, что за шаг открылся */
export function useFocusOnMount<T extends HTMLElement>() {
  const ref = useRef<T>(null);
  useEffect(() => {
    ref.current?.focus({ preventScroll: true });
  }, []);
  return ref;
}
