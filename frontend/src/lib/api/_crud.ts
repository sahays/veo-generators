import { patchJson, request, requestVoid } from './_http'

export interface CrudClient<T> {
  list: (qs?: string) => Promise<T[]>
  get: (id: string) => Promise<T>
  update: (id: string, data: Record<string, any>) => Promise<void>
  archive: (id: string) => Promise<void>
  unarchive: (id: string) => Promise<void>
  delete: (id: string) => Promise<void>
  retry: (id: string) => Promise<any>
}

export function createCrudClient<T = any>(
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
      request<any>(`${base}/${id}/retry`, `Failed to retry ${label}`, {
        method: 'POST',
      }),
  }
}
