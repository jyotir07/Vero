/**
 * Typed access to the Vero API.
 *
 * Every shape here comes from schema.d.ts, which is generated from the backend's
 * OpenAPI document. Nothing in this file hand-writes a request or response type, so a
 * change to a Pydantic model shows up as a TypeScript error rather than a runtime
 * surprise.
 */

import type { components } from './schema'

export type ApplicationRead = components['schemas']['ApplicationRead']
export type ApplicationSummary = components['schemas']['ApplicationSummary']
export type ApplicationCreate = components['schemas']['ApplicationCreate']
export type WorkflowEventRead = components['schemas']['WorkflowEventRead']
export type DocumentRead = components['schemas']['DocumentRead']
export type RiskAssessmentRead = components['schemas']['RiskAssessmentRead']
export type ApplicationState = ApplicationRead['state']
export type DocumentType = DocumentRead['document_type']

const BASE = '/api'

export class ApiError extends Error {
  // Declared rather than a constructor parameter property: tsconfig sets
  // erasableSyntaxOnly, which forbids syntax that needs a runtime transform.
  status: number

  constructor(status: number, message: string) {
    super(message)
    this.status = status
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${BASE}${path}`, init)
  if (!response.ok) {
    // FastAPI returns {detail: ...}; detail may be a string or a validation array.
    let detail = response.statusText
    try {
      const body = await response.json()
      detail = typeof body.detail === 'string' ? body.detail : JSON.stringify(body.detail)
    } catch {
      // Body was not JSON; the status text is the best we have.
    }
    throw new ApiError(response.status, detail)
  }
  return (await response.json()) as T
}

export const api = {
  listApplications: () => request<ApplicationSummary[]>('/applications'),

  getApplication: (id: string) => request<ApplicationRead>(`/applications/${id}`),

  listEvents: (id: string) => request<WorkflowEventRead[]>(`/applications/${id}/events`),

  createApplication: (payload: ApplicationCreate) =>
    request<ApplicationRead>('/applications', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    }),

  uploadDocument: (id: string, documentType: DocumentType, file: File) => {
    const form = new FormData()
    form.append('document_type', documentType)
    form.append('file', file)
    return request<DocumentRead>(`/applications/${id}/documents`, {
      method: 'POST',
      body: form,
    })
  },
}

export const TERMINAL_STATES: ApplicationState[] = ['APPROVED', 'REJECTED', 'FAILED']

/**
 * Waiting on a person, but not finished.
 *
 * These look settled and are not: a document arriving or a reviewer deciding moves the
 * application on. Treating them as final leaves the page showing a state the backend
 * has already left behind, so polling slows down here rather than stopping.
 */
export const WAITING_STATES: ApplicationState[] = [
  'HUMAN_REVIEW',
  'MORE_INFORMATION_REQUIRED',
]

export function isTerminal(state: ApplicationState): boolean {
  return TERMINAL_STATES.includes(state)
}

export function isWaiting(state: ApplicationState): boolean {
  return WAITING_STATES.includes(state)
}

export function formatInr(paise: number): string {
  return new Intl.NumberFormat('en-IN', {
    style: 'currency',
    currency: 'INR',
    maximumFractionDigits: 2,
  }).format(paise / 100)
}

export function formatPercent(ratio: string): string {
  return `${(Number(ratio) * 100).toFixed(1)}%`
}
