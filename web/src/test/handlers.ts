import { http } from 'msw';
import {
  getHealthDepsMockHandler,
  getHealthLiveMockHandler,
  getHealthReadyMockHandler,
} from '@/api/generated/api.msw';
import { makePublicConfig, problemResponse } from './factories';

/**
 * Обработчики по умолчанию: пока в api нет входа, `/me` отвечает «не вошли» (401), как и будет без сессии.
 * Обработчики ручек из схемы берутся из сгенерированных файлов `*.msw.ts` и обновляются вместе с клиентом.
 */
export const defaultHandlers = [
  getHealthLiveMockHandler(),
  getHealthReadyMockHandler(),
  getHealthDepsMockHandler(),
  http.get('*/api/me', () => problemResponse({ status: 401, code: 'UNAUTHENTICATED' })),
  http.get('*/api/applications', () => Response.json({ items: [], nextCursor: null })),
  http.get('*/api/loans', () => Response.json({ items: [], nextCursor: null })),
  http.get('*/api/public-config', () => Response.json(makePublicConfig({ demoMode: false }))),
];
