import { createContext, useContext } from 'react';
import type { StreamStatus } from './useEventStream';

/** Состояние связи для индикатора в шапке; хук потока вызывается один раз, остальные только читают */
export const ConnectionContext = createContext<StreamStatus>('connecting');

export function useConnectionStatus(): StreamStatus {
  return useContext(ConnectionContext);
}
