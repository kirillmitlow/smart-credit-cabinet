/** Зона интерфейса определяет, какая из двух независимых сессий используется (D-085): `sid_client` или `sid_bank`. */
export type Zone = 'client' | 'bank';

export function zoneFromPath(pathname: string): Zone {
  return pathname === '/bank' || pathname.startsWith('/bank/') ? 'bank' : 'client';
}

export function currentZone(): Zone {
  if (
    window.location.pathname === '/login' &&
    new URLSearchParams(window.location.search).get('zone') === 'bank'
  )
    return 'bank';
  return zoneFromPath(window.location.pathname);
}
