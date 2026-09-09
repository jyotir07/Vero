/**
 * Polls an application while the workflow is still working on it.
 *
 * Phase 1 runs the agent in-process, so there is no stream to subscribe to.
 *
 * Polling stops only on a terminal state. States that merely wait on a person look
 * final and are not: an upload or a reviewer decision moves the application on, and a
 * page that stopped polling would sit on a state the backend had already left. Those
 * are polled slowly rather than not at all.
 */

import { useCallback, useEffect, useRef, useState } from 'react'

import {
  api,
  isTerminal,
  isWaiting,
  type ApplicationRead,
  type WorkflowEventRead,
} from '@/api/client'

const TICK_MS = 1500
/** Waiting states change on someone else's schedule, so check less often, not never. */
const TICKS_WHILE_WAITING = 4

interface ApplicationData {
  application: ApplicationRead | null
  events: WorkflowEventRead[]
  loading: boolean
  error: string | null
  refresh: () => Promise<void>
}

export function useApplication(id: string | undefined): ApplicationData {
  const [application, setApplication] = useState<ApplicationRead | null>(null)
  const [events, setEvents] = useState<WorkflowEventRead[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  // Kept in refs so the polling effect does not restart on every state change.
  const finished = useRef(false)
  const waiting = useRef(false)
  const tick = useRef(0)

  const refresh = useCallback(async () => {
    if (!id) return
    try {
      const [next, nextEvents] = await Promise.all([api.getApplication(id), api.listEvents(id)])
      setApplication(next)
      setEvents(nextEvents)
      finished.current = isTerminal(next.state)
      waiting.current = isWaiting(next.state)
      setError(null)
    } catch (err) {
      setError(err instanceof Error ? err.message : 'could not load application')
    } finally {
      setLoading(false)
    }
  }, [id])

  useEffect(() => {
    if (!id) return
    finished.current = false
    waiting.current = false
    tick.current = 0
    setLoading(true)
    void refresh()

    const timer = window.setInterval(() => {
      if (finished.current) return
      tick.current += 1
      if (waiting.current && tick.current % TICKS_WHILE_WAITING !== 0) return
      void refresh()
    }, TICK_MS)
    return () => window.clearInterval(timer)
  }, [id, refresh])

  return { application, events, loading, error, refresh }
}

export function useApplicationList(): {
  applications: Awaited<ReturnType<typeof api.listApplications>>
  loading: boolean
  error: string | null
  refresh: () => Promise<void>
} {
  const [applications, setApplications] = useState<
    Awaited<ReturnType<typeof api.listApplications>>
  >([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  const refresh = useCallback(async () => {
    try {
      setApplications(await api.listApplications())
      setError(null)
    } catch (err) {
      setError(err instanceof Error ? err.message : 'could not load applications')
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    void refresh()
  }, [refresh])

  return { applications, loading, error, refresh }
}
