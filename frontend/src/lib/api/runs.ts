/**
 * Async-run status client — mirrors `productions_service/services/jobs/contract.py`.
 * All calls go server-to-server through `serverApiRequest` (via `request`).
 */
import { API_BASE_URL, request } from './core/_http'
import type { ProductionStatusResponse } from '@/types/runs'

export * from '@/types/runs'

export const runs = {
  /** Cheap (<150 ms) status read: active run, last finished run, server clock. Safe to poll. */
  getStatus: (pid: string): Promise<ProductionStatusResponse> =>
    request<ProductionStatusResponse>(
      `${API_BASE_URL}/productions/${encodeURIComponent(pid)}/status`,
      'Failed to load production status',
    ),
}
