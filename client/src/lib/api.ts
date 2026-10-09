const API_URL = import.meta.env.VITE_API_URL ?? 'http://localhost:8000'

export type HealthResponse = {
  status: string
}

export async function getHealth(signal?: AbortSignal): Promise<HealthResponse> {
  const response = await fetch(`${API_URL}/health`, { signal })
  if (!response.ok) {
    throw new Error(`backend responded ${response.status}`)
  }
  return response.json() as Promise<HealthResponse>
}
