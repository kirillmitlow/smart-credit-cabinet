import { http } from 'msw';
import { getHealthMock } from '@/api/generated/endpoints/health/health.msw';
import { makePublicConfig, problemResponse } from './factories';

/**
 * Обработчики по умолчанию: пока в api нет входа, `/me` отвечает «не вошли» (401), как и будет без сессии.
 * Обработчики ручек из схемы берутся из сгенерированных файлов `*.msw.ts` и обновляются вместе с клиентом.
 */
export const defaultHandlers = [
  ...getHealthMock(),
  http.get('*/api/v1/me', () => problemResponse({ status: 401, code: 'UNAUTHENTICATED' })),
  http.get('*/api/v1/public-config', () => Response.json(makePublicConfig({ demoMode: false }))),
];
