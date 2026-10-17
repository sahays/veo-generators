import { api } from '@/lib/api'

export { api }

export function useApiClient(): typeof api {
  return api
}
