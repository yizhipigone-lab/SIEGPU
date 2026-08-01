import { api } from '../api/client'

export async function listRes(path: string, params?: Record<string, unknown>) {
  const { data } = await api.get(path, { params })
  return data as { items: any[]; total: number }
}
export async function createRes(path: string, body: unknown) {
  const { data } = await api.post(path, body)
  return data
}
export async function updateRes(path: string, id: string, body: unknown) {
  const { data } = await api.patch(`${path}/${id}`, body)
  return data
}
export async function deleteRes(path: string, id: string) {
  await api.delete(`${path}/${id}`)
}
