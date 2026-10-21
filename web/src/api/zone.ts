/** Зона интерфейса определяет, какая из двух независимых сессий используется (D-085): `sid_client` или `sid_bank`. */
export type Zone = 'client' | 'bank';

export function zoneFromPath(pathname: string): Zone {
  return pathname === '/bank' || pathname.startsWith('/bank/') ? 'bank' : 'client';
}

export function currentZone(): Zone {
  return zoneFromPath(window.location.pathname);
}
