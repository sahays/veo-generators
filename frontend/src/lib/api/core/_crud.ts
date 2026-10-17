import { type JsonValue, patchJson, request, requestVoid } from './_http'

export interface CrudClient<T = JsonValue> {
  list: (qs?: string) => Promise<T[]>
  get: (id: string) => Promise<T>
  update: (id: string, data: Record<string, JsonValue>) => Promise<void>
  archive: (id: string) => Promise<void>
  unarchive: (id: string) => Promise<void>
  delete: (id: string) => Promise<void>
  retry: (id: string) => Promise<JsonValue>
}

export function createCrudClient<T = JsonValue>(
  base: string,
  label: string,
): CrudClient<T> {
  return {
    list: (qs = '') =>
      request<T[]>(`${base}${qs ? `?${qs}` : ''}`, `Failed to list ${label}s`),
    get: (id) => request<T>(`${base}/${id}`, `Failed to get ${label}`),
    update: (id, data) =>
      patchJson(`${base}/${id}`, data, `Failed to update ${label}`),
    archive: (id) =>
      requestVoid(`${base}/${id}/archive`, `Failed to archive ${label}`, {
        method: 'POST',
      }),
    unarchive: (id) =>
      requestVoid(`${base}/${id}/unarchive`, `Failed to unarchive ${label}`, {
        method: 'POST',
      }),
    delete: (id) =>
      requestVoid(`${base}/${id}`, `Failed to delete ${label}`, {
        method: 'DELETE',
      }),
    retry: (id) =>
      request<JsonValue>(`${base}/${id}/retry`, `Failed to retry ${label}`, {
        method: 'POST',
      }),
  }
}
