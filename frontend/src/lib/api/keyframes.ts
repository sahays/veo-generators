/**
 * S8_KEYFRAMES client — mirrors `productions_service/services/keyframes_contract.py` 1:1.
 * All calls go server-to-server through `serverApiRequest` (via `request` / `postJson`).
 */
import { API_BASE_URL, postJson, request } from './core/_http'
import { KEYFRAME_INSTRUCTION_MAX, type KeyframeBoardResponse, type KeyframeStripResponse, type RegenerateKeyframePayload } from '@/types/keyframes'

export * from '@/types/keyframes'

const productionPath = (pid: string): string =>
  `${API_BASE_URL}/productions/${encodeURIComponent(pid)}`

const shotKeyframesPath = (pid: string, shotId: string): string =>
  `${productionPath(pid)}/shots/${encodeURIComponent(shotId)}/keyframes`

export const keyframes = {
  getBoard: (pid: string): Promise<KeyframeBoardResponse> =>
    request<KeyframeBoardResponse>(`${productionPath(pid)}/keyframes`, 'Failed to load keyframes'),
  getStrip: (pid: string, shotId: string): Promise<KeyframeStripResponse> =>
    request<KeyframeStripResponse>(shotKeyframesPath(pid, shotId), 'Failed to load shot keyframes'),
  regenerateFrom: (
    pid: string,
    shotId: string,
    t: number,
    payload: RegenerateKeyframePayload = {},
  ): Promise<KeyframeStripResponse> =>
    postJson<KeyframeStripResponse>(
      `${shotKeyframesPath(pid, shotId)}/${t}/regenerate`,
      { instruction: (payload.instruction ?? '').slice(0, KEYFRAME_INSTRUCTION_MAX) },
      'Failed to regenerate keyframes',
    ),
}
