/**
 * The pieces that make the state machine visible.
 *
 * The stepper and timeline exist to show that the workflow is genuinely stateful:
 * every position and every row comes from persisted data, not from client-side
 * bookkeeping about what probably happened.
 */

import {
  AlertTriangle,
  Ban,
  Bot,
  CheckCircle2,
  CircleDashed,
  Clock,
  FileText,
  User,
  UserCog,
} from 'lucide-react'
import type { ReactNode } from 'react'

import {
  formatInr,
  formatPercent,
  type ApplicationState,
  type RiskAssessmentRead,
  type WorkflowEventRead,
} from '@/api/client'
import { Badge } from '@/components/ui/badge'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Separator } from '@/components/ui/separator'

/** The order an application moves through. Terminal and pause states sit outside it. */
const MAIN_PATH: ApplicationState[] = [
  'RECEIVED',
  'DOCUMENT_CHECK',
  'INCOME_VERIFICATION',
  'CREDIT_ANALYSIS',
  'RISK_ASSESSMENT',
  'DECISION',
]

const STATE_LABEL: Record<ApplicationState, string> = {
  RECEIVED: 'Received',
  DOCUMENT_CHECK: 'Document check',
  INCOME_VERIFICATION: 'Income verification',
  CREDIT_ANALYSIS: 'Credit analysis',
  RISK_ASSESSMENT: 'Risk assessment',
  HUMAN_REVIEW: 'Human review',
  DECISION: 'Decision',
  APPROVED: 'Approved',
  REJECTED: 'Rejected',
  MORE_INFORMATION_REQUIRED: 'More information required',
  FAILED: 'Failed',
}

type BadgeVariant = 'default' | 'secondary' | 'destructive' | 'outline'

const STATE_VARIANT: Record<ApplicationState, BadgeVariant> = {
  RECEIVED: 'secondary',
  DOCUMENT_CHECK: 'secondary',
  INCOME_VERIFICATION: 'secondary',
  CREDIT_ANALYSIS: 'secondary',
  RISK_ASSESSMENT: 'secondary',
  HUMAN_REVIEW: 'outline',
  DECISION: 'secondary',
  APPROVED: 'default',
  REJECTED: 'destructive',
  MORE_INFORMATION_REQUIRED: 'outline',
  FAILED: 'destructive',
}

export function StateBadge({ state }: { state: ApplicationState }) {
  return <Badge variant={STATE_VARIANT[state]}>{STATE_LABEL[state]}</Badge>
}

export function WorkflowStepper({ state }: { state: ApplicationState }) {
  const settledIndex = MAIN_PATH.indexOf(state)
  const isOffPath = settledIndex === -1
  // Approved and rejected are reached through DECISION, so the whole path is behind them.
  const reached = isOffPath && state !== 'FAILED' ? MAIN_PATH.length : settledIndex

  return (
    <ol className="flex flex-wrap items-center gap-x-2 gap-y-3">
      {MAIN_PATH.map((step, index) => {
        const done = index < reached
        const current = index === reached
        return (
          <li key={step} className="flex items-center gap-2">
            <span
              className={
                'flex items-center gap-1.5 rounded-md border px-2.5 py-1 text-xs font-medium ' +
                (done
                  ? 'border-transparent bg-primary/10 text-foreground'
                  : current
                    ? 'border-ring bg-background text-foreground'
                    : 'border-border bg-background text-muted-foreground')
              }
            >
              {done ? (
                <CheckCircle2 className="h-3.5 w-3.5" aria-hidden />
              ) : current ? (
                <Clock className="h-3.5 w-3.5" aria-hidden />
              ) : (
                <CircleDashed className="h-3.5 w-3.5" aria-hidden />
              )}
              {STATE_LABEL[step]}
            </span>
            {index < MAIN_PATH.length - 1 && (
              <span aria-hidden className="h-px w-4 bg-border" />
            )}
          </li>
        )
      })}
      {isOffPath && (
        <li className="ml-1">
          <StateBadge state={state} />
        </li>
      )}
    </ol>
  )
}

const ACTOR_ICON: Record<string, ReactNode> = {
  AGENT: <Bot className="h-4 w-4" aria-hidden />,
  SYSTEM: <UserCog className="h-4 w-4" aria-hidden />,
  APPLICANT: <User className="h-4 w-4" aria-hidden />,
  REVIEWER: <UserCog className="h-4 w-4" aria-hidden />,
}

function describe(event: WorkflowEventRead): string {
  const payload = event.payload as Record<string, unknown>
  switch (event.event_type) {
    case 'STATE_CHANGED':
      return `${STATE_LABEL[event.from_state as ApplicationState] ?? '—'} → ${
        STATE_LABEL[event.to_state as ApplicationState] ?? '—'
      }`
    case 'AGENT_ACTION_PROPOSED':
      return `Proposed ${String(payload.tool ?? 'an action')} (${String(payload.result ?? '')})`
    case 'AGENT_ACTION_REJECTED':
      return `Refused: ${String(payload.reason ?? 'invalid proposal')}`
    case 'TOOL_CALL_STARTED':
      return `Calling ${String(payload.tool ?? '')}`
    case 'TOOL_CALL_SUCCEEDED':
      return `${String(payload.tool ?? 'tool')} succeeded`
    case 'TOOL_CALL_FAILED':
      return `${String(payload.tool ?? 'tool')} failed: ${String(payload.error ?? '')}`
    case 'DOCUMENT_UPLOADED':
      return `Uploaded ${String(payload.document_type ?? 'a document')}`
    case 'DECISION_MADE':
      return `Outcome ${String(payload.outcome ?? '')}${
        payload.reason ? ` — ${String(payload.reason)}` : ''
      }`
    default:
      return event.event_type.replaceAll('_', ' ').toLowerCase()
  }
}

export function Timeline({ events }: { events: WorkflowEventRead[] }) {
  if (events.length === 0) {
    return <p className="text-sm text-muted-foreground">Nothing has happened yet.</p>
  }

  return (
    <ol className="space-y-0">
      {events.map((event, index) => {
        const refused = event.event_type === 'AGENT_ACTION_REJECTED'
        return (
          <li key={event.seq} className="flex gap-3">
            <div className="flex flex-col items-center">
              <span
                className={
                  'flex h-7 w-7 shrink-0 items-center justify-center rounded-full border ' +
                  (refused
                    ? 'border-destructive/40 text-destructive'
                    : 'border-border text-muted-foreground')
                }
              >
                {ACTOR_ICON[event.actor] ?? <FileText className="h-4 w-4" aria-hidden />}
              </span>
              {index < events.length - 1 && <span className="w-px flex-1 bg-border" />}
            </div>
            <div className="pb-4">
              <p className="text-sm text-foreground">{describe(event)}</p>
              <p className="font-mono text-xs text-muted-foreground">
                #{event.seq} · {event.actor.toLowerCase()} ·{' '}
                {new Date(event.created_at).toLocaleTimeString()}
              </p>
            </div>
          </li>
        )
      })}
    </ol>
  )
}

const BAND_STYLE: Record<string, string> = {
  PASS: 'text-foreground',
  REVIEW: 'text-foreground',
  FAIL: 'text-destructive',
}

const GATE_LABEL: Record<string, string> = {
  CREDIT_SCORE: 'Credit score',
  DTI: 'Debt to income',
  LTI: 'Loan to income',
  DISPOSABLE_INCOME: 'Disposable income',
  INCOME_DIVERGENCE: 'Income verification',
}

export function RiskPanel({ assessment }: { assessment: RiskAssessmentRead }) {
  const figures: Array<[string, string]> = [
    ['Credit score', String(assessment.credit_score)],
    ['Monthly instalment', formatInr(assessment.emi)],
    ['DTI before loan', formatPercent(assessment.dti_current)],
    ['DTI after loan', formatPercent(assessment.dti_proposed)],
    ['Loan to income', `${Number(assessment.lti).toFixed(2)}x`],
    ['Disposable income', formatInr(assessment.disposable_income)],
  ]

  return (
    <Card>
      <CardHeader>
        <CardTitle className="text-base">Risk assessment</CardTitle>
      </CardHeader>
      <CardContent className="space-y-4">
        <dl className="grid grid-cols-2 gap-x-4 gap-y-3">
          {figures.map(([label, value]) => (
            <div key={label}>
              <dt className="text-xs text-muted-foreground">{label}</dt>
              <dd className="font-mono text-sm text-foreground">{value}</dd>
            </div>
          ))}
        </dl>

        <Separator />

        <ul className="space-y-1.5">
          {Object.entries(assessment.gate_bands).map(([gate, band]) => (
            <li key={gate} className="flex items-center justify-between text-sm">
              <span className="text-muted-foreground">{GATE_LABEL[gate] ?? gate}</span>
              <span className={`font-mono text-xs ${BAND_STYLE[band] ?? ''}`}>
                {band === 'PASS' && <CheckCircle2 className="mr-1 inline h-3.5 w-3.5" />}
                {band === 'REVIEW' && <AlertTriangle className="mr-1 inline h-3.5 w-3.5" />}
                {band === 'FAIL' && <Ban className="mr-1 inline h-3.5 w-3.5" />}
                {band}
              </span>
            </li>
          ))}
        </ul>
      </CardContent>
    </Card>
  )
}
