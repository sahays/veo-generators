/**
 * Blender previz client — mirrors the productions-service `/previz` contract 1:1.
 * All calls go server-to-server through `serverApiRequest` (via `request` / `postJson`).
 */
import { API_BASE_URL, postJson, request } from './core/_http'
import type {
  PrevizBoardResponse,
  PrevizPromotePayload,
  PrevizRunAccepted,
  PrevizRunPayload,
  ShotPreviz,
} from '@/types/previz'

export * from '@/types/previz'

const previzPath = (pid: string): string =>
  `${API_BASE_URL}/productions/${encodeURIComponent(pid)}/previz`

export const previz = {
  getBoard: (pid: string): Promise<PrevizBoardResponse> =>
    request<PrevizBoardResponse>(previzPath(pid), 'Failed to load previz'),
  run: (pid: string, payload: PrevizRunPayload): Promise<PrevizRunAccepted> =>
    postJson<PrevizRunAccepted>(`${previzPath(pid)}/run`, payload, 'Failed to start previz run'),
  promote: (pid: string, shotId: string, payload: PrevizPromotePayload): Promise<ShotPreviz> =>
    postJson<ShotPreviz>(
      `${previzPath(pid)}/shots/${encodeURIComponent(shotId)}/promote`,
      payload,
      'Failed to promote render',
    ),
}
