import { useState } from 'react'
import { useNavigate } from 'react-router-dom'

import { api, formatInr, type ApplicationCreate } from '@/api/client'
import { Alert, AlertDescription } from '@/components/ui/alert'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select'

const TENURES = [12, 24, 36, 48, 60]

/**
 * Preset applicants that reach each outcome on purpose.
 *
 * The first two are the spec's worked example at two tenures: the same person approves
 * over 60 months and goes to a reviewer over 36. Having them one click away means the
 * demo does not depend on typing the right numbers under pressure.
 */
const PRESETS: Array<{ label: string; hint: string; values: Partial<FormState> }> = [
  {
    label: 'Approves',
    hint: 'Worked example, 60 months',
    values: { name: 'Asha Iyer', income: '150000', debt: '35000', amount: '800000', tenure: 60, score: '742' },
  },
  {
    label: 'Goes to review',
    hint: 'Same applicant, 36 months',
    values: { name: 'Asha Iyer', income: '150000', debt: '35000', amount: '800000', tenure: 36, score: '742' },
  },
  {
    label: 'Is rejected',
    hint: 'Credit score below the floor',
    values: { name: 'Meera Nair', income: '60000', debt: '20000', amount: '900000', tenure: 60, score: '600' },
  },
]

interface FormState {
  name: string
  email: string
  income: string
  debt: string
  amount: string
  tenure: number
  score: string
}

const INITIAL: FormState = {
  name: 'Asha Iyer',
  email: 'asha@example.com',
  income: '150000',
  debt: '35000',
  amount: '800000',
  tenure: 60,
  score: '742',
}

/** The form works in rupees; the API works in paise. Converted once, here. */
function toPaise(rupees: string): number {
  return Math.round(Number(rupees) * 100)
}

export function NewApplication() {
  const navigate = useNavigate()
  const [form, setForm] = useState<FormState>(INITIAL)
  const [error, setError] = useState<string | null>(null)
  const [submitting, setSubmitting] = useState(false)

  const set = (patch: Partial<FormState>) => setForm((current) => ({ ...current, ...patch }))

  async function submit(event: React.FormEvent) {
    event.preventDefault()
    setSubmitting(true)
    setError(null)
    const payload: ApplicationCreate = {
      applicant_name: form.name,
      applicant_email: form.email,
      gross_monthly_income_paise: toPaise(form.income),
      monthly_debt_paise: toPaise(form.debt),
      requested_amount_paise: toPaise(form.amount),
      tenure_months: form.tenure,
      synthetic_credit_score: form.score ? Number(form.score) : null,
    }
    try {
      const created = await api.createApplication(payload)
      navigate(`/applications/${created.id}`)
    } catch (err) {
      setError(err instanceof Error ? err.message : 'could not create the application')
      setSubmitting(false)
    }
  }

  return (
    <div className="mx-auto max-w-2xl space-y-6">
      <div>
        <h1 className="text-2xl font-semibold tracking-tight text-foreground">New application</h1>
        <p className="text-sm text-muted-foreground">
          All figures are synthetic. Documents are uploaded on the next screen.
        </p>
      </div>

      <div className="flex flex-wrap gap-2">
        {PRESETS.map((preset) => (
          <Button
            key={preset.label}
            type="button"
            variant="outline"
            size="sm"
            onClick={() => set(preset.values)}
          >
            {preset.label}
            <span className="text-muted-foreground">· {preset.hint}</span>
          </Button>
        ))}
      </div>

      <Card>
        <CardHeader>
          <CardTitle className="text-base">Applicant</CardTitle>
        </CardHeader>
        <CardContent>
          <form onSubmit={submit} className="grid gap-4 sm:grid-cols-2">
            <div className="space-y-2">
              <Label htmlFor="name">Name</Label>
              <Input id="name" value={form.name} onChange={(e) => set({ name: e.target.value })} required />
            </div>
            <div className="space-y-2">
              <Label htmlFor="email">Email</Label>
              <Input id="email" type="email" value={form.email} onChange={(e) => set({ email: e.target.value })} required />
            </div>
            <div className="space-y-2">
              <Label htmlFor="income">Gross monthly income (₹)</Label>
              <Input id="income" inputMode="numeric" value={form.income} onChange={(e) => set({ income: e.target.value })} required />
            </div>
            <div className="space-y-2">
              <Label htmlFor="debt">Existing monthly debt (₹)</Label>
              <Input id="debt" inputMode="numeric" value={form.debt} onChange={(e) => set({ debt: e.target.value })} required />
            </div>
            <div className="space-y-2">
              <Label htmlFor="amount">Loan amount (₹)</Label>
              <Input id="amount" inputMode="numeric" value={form.amount} onChange={(e) => set({ amount: e.target.value })} required />
              <p className="text-xs text-muted-foreground">
                {formatInr(toPaise(form.amount) || 0)} over {form.tenure} months at 14% p.a.
              </p>
            </div>
            <div className="space-y-2">
              <Label htmlFor="tenure">Tenure</Label>
              <Select value={String(form.tenure)} onValueChange={(v) => set({ tenure: Number(v) })}>
                <SelectTrigger id="tenure">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  {TENURES.map((months) => (
                    <SelectItem key={months} value={String(months)}>
                      {months} months
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
            <div className="space-y-2 sm:col-span-2">
              <Label htmlFor="score">Synthetic credit score</Label>
              <Input id="score" inputMode="numeric" value={form.score} onChange={(e) => set({ score: e.target.value })} />
              <p className="text-xs text-muted-foreground">
                Seeds the simulated bureau so a run reaches a chosen outcome. Leave blank for a
                score derived from the application id.
              </p>
            </div>

            {error && (
              <div className="sm:col-span-2">
                <Alert variant="destructive">
                  <AlertDescription>{error}</AlertDescription>
                </Alert>
              </div>
            )}

            <div className="sm:col-span-2">
              <Button type="submit" disabled={submitting}>
                {submitting ? 'Submitting…' : 'Submit application'}
              </Button>
            </div>
          </form>
        </CardContent>
      </Card>
    </div>
  )
}
