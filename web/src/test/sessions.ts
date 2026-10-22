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

/** Две независимые сессии (D-085): маршруты клиента и банка читают только свой контекст. */
export function mockSessions({ client = null, bank = null, config = {} }: SessionsInit = {}) {
  server.use(
    http.get('*/api/me', () =>
      client ? Response.json(client) : problemResponse({ status: 401, code: 'UNAUTHENTICATED' }),
    ),
    http.get('*/api/auth/bank-me', () =>
      bank
        ? Response.json({ ...bank, level: bank.level ?? 'L2' })
        : problemResponse({ status: 401, code: 'UNAUTHENTICATED' }),
    ),
    http.get('*/api/public-config', () => Response.json(makePublicConfig(config))),
  );
}
