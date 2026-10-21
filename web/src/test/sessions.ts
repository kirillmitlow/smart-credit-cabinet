import { http } from 'msw';
import type { PublicConfig } from '@/api/generated/model';
import type { Me } from '@/features/auth/session';
import { makePublicConfig, problemResponse } from './factories';
import { server } from './server';

export interface SessionsInit {
  /** Клиентская сессия (`sid_client`); null — не вошёл */
  client?: Me | null;
  /** Банковская сессия (`sid_bank`) */
  bank?: Me | null;
  config?: Partial<PublicConfig>;
}

/** Две независимые сессии (D-085): `GET /me?zone=…` отвечает по зоне, без сессии — 401 */
export function mockSessions({ client = null, bank = null, config = {} }: SessionsInit = {}) {
  server.use(
    http.get('*/api/me', ({ request }) => {
      const zone = new URL(request.url).searchParams.get('zone');
      const me = zone === 'bank' ? bank : client;
      return me ? Response.json(me) : problemResponse({ status: 401, code: 'UNAUTHENTICATED' });
    }),
    http.get('*/api/public-config', () => Response.json(makePublicConfig(config))),
  );
}
