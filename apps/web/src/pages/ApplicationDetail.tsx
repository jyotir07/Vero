import { ArrowLeft, CheckCircle2, CircleAlert, Loader2, Upload } from 'lucide-react'
import { useRef, useState } from 'react'
import { Link, useParams } from 'react-router-dom'

import { api, formatInr, isTerminal, type DocumentType } from '@/api/client'
import { RiskPanel, StateBadge, Timeline, WorkflowStepper } from '@/components/workflow'
import { Alert, AlertDescription } from '@/components/ui/alert'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Separator } from '@/components/ui/separator'
import { Skeleton } from '@/components/ui/skeleton'
import { useApplication } from '@/hooks/useApplication'

const DOCUMENT_LABEL: Record<DocumentType, string> = {
  PAY_SLIP: 'Payslip',
  BANK_STATEMENT: 'Bank statement',
  ID_PROOF: 'Identity document',
}

const ALL_DOCUMENTS: DocumentType[] = ['PAY_SLIP', 'BANK_STATEMENT', 'ID_PROOF']

export function ApplicationDetail() {
  const { id } = useParams<{ id: string }>()
  const { application, events, loading, error, refresh } = useApplication(id)
  const [uploading, setUploading] = useState<DocumentType | null>(null)
  const [uploadError, setUploadError] = useState<string | null>(null)
  const inputs = useRef<Partial<Record<DocumentType, HTMLInputElement | null>>>({})

  async function upload(documentType: DocumentType, file: File) {
    if (!id) return
    setUploading(documentType)
    setUploadError(null)
    try {
      await api.uploadDocument(id, documentType, file)
      await refresh()
    } catch (err) {
      setUploadError(err instanceof Error ? err.message : 'upload failed')
    } finally {
      setUploading(null)
    }
  }

  if (loading && !application) {
    return (
      <div className="space-y-4">
        <Skeleton className="h-8 w-64" />
        <Skeleton className="h-32 w-full" />
      </div>
    )
  }

  if (error && !application) {
    return (
      <Alert variant="destructive">
        <AlertDescription>{error}</AlertDescription>
      </Alert>
    )
  }

  if (!application) return null

  const byType = new Map(application.documents.map((d) => [d.document_type, d]))
  const working = !isTerminal(application.state)

  return (
    <div className="space-y-6">
      <div>
        <Button asChild variant="ghost" size="sm" className="-ml-2 mb-2">
          <Link to="/">
            <ArrowLeft className="h-4 w-4" aria-hidden />
            All applications
          </Link>
        </Button>
        <div className="flex flex-wrap items-center gap-3">
          <h1 className="text-2xl font-semibold tracking-tight text-foreground">
            {application.applicant_name}
          </h1>
          <StateBadge state={application.state} />
          {working && (
            <span className="flex items-center gap-1.5 text-xs text-muted-foreground">
              <Loader2 className="h-3.5 w-3.5 animate-spin" aria-hidden />
              working…
            </span>
          )}
        </div>
        <p className="font-mono text-sm text-muted-foreground">
          {formatInr(application.requested_amount_paise)} over {application.tenure_months} months
          · {(application.annual_rate_bps / 100).toFixed(1)}% p.a.
        </p>
      </div>

      <Card>
        <CardContent className="pt-6">
          <WorkflowStepper state={application.state} />
        </CardContent>
      </Card>

      <div className="grid gap-6 lg:grid-cols-3">
        <div className="space-y-6 lg:col-span-2">
          <Card>
            <CardHeader>
              <CardTitle className="text-base">Documents</CardTitle>
            </CardHeader>
            <CardContent className="space-y-3">
              {application.state === 'MORE_INFORMATION_REQUIRED' && (
                <Alert>
                  <AlertDescription>
                    The agent is waiting for{' '}
                    {application.missing_documents
                      .map((d) => DOCUMENT_LABEL[d].toLowerCase())
                      .join(', ')}
                    .
                  </AlertDescription>
                </Alert>
              )}
              {uploadError && (
                <Alert variant="destructive">
                  <AlertDescription>{uploadError}</AlertDescription>
                </Alert>
              )}

              <ul className="divide-y divide-border">
                {ALL_DOCUMENTS.map((documentType) => {
                  const document = byType.get(documentType)
                  const failed = document?.status === 'EXTRACTION_FAILED'
                  return (
                    <li
                      key={documentType}
                      className="flex items-center justify-between gap-3 py-3"
                    >
                      <div className="flex items-center gap-2">
                        {document ? (
                          failed ? (
                            <CircleAlert className="h-4 w-4 text-destructive" aria-hidden />
                          ) : (
                            <CheckCircle2 className="h-4 w-4 text-muted-foreground" aria-hidden />
                          )
                        ) : (
                          <Upload className="h-4 w-4 text-muted-foreground" aria-hidden />
                        )}
                        <div>
                          <p className="text-sm text-foreground">
                            {DOCUMENT_LABEL[documentType]}
                          </p>
                          <p className="font-mono text-xs text-muted-foreground">
                            {document
                              ? `${document.status.toLowerCase()}${
                                  document.extraction_confidence
                                    ? ` · confidence ${document.extraction_confidence}`
                                    : ''
                                }`
                              : 'not provided'}
                          </p>
                        </div>
                      </div>

                      <div>
                        <input
                          ref={(el) => {
                            inputs.current[documentType] = el
                          }}
                          type="file"
                          accept="application/pdf"
                          className="hidden"
                          onChange={(e) => {
                            const file = e.target.files?.[0]
                            if (file) void upload(documentType, file)
                            e.target.value = ''
                          }}
                        />
                        <Button
                          type="button"
                          variant="outline"
                          size="sm"
                          disabled={uploading !== null}
                          onClick={() => inputs.current[documentType]?.click()}
                        >
                          {uploading === documentType
                            ? 'Uploading…'
                            : document
                              ? 'Replace'
                              : 'Upload'}
                        </Button>
                      </div>
                    </li>
                  )
                })}
              </ul>
            </CardContent>
          </Card>

          <Card>
            <CardHeader>
              <CardTitle className="text-base">Workflow timeline</CardTitle>
            </CardHeader>
            <CardContent>
              <Timeline events={events} />
            </CardContent>
          </Card>
        </div>

        <div className="space-y-6">
          {application.risk_assessment ? (
            <RiskPanel assessment={application.risk_assessment} />
          ) : (
            <Card>
              <CardHeader>
                <CardTitle className="text-base">Risk assessment</CardTitle>
              </CardHeader>
              <CardContent>
                <p className="text-sm text-muted-foreground">
                  Not yet reached. The agent assesses risk once documents are verified.
                </p>
              </CardContent>
            </Card>
          )}

          <Card>
            <CardHeader>
              <CardTitle className="text-base">Applicant</CardTitle>
            </CardHeader>
            <CardContent>
              <dl className="space-y-3">
                <div>
                  <dt className="text-xs text-muted-foreground">Email</dt>
                  <dd className="text-sm text-foreground">{application.applicant_email}</dd>
                </div>
                <Separator />
                <div>
                  <dt className="text-xs text-muted-foreground">Gross monthly income</dt>
                  <dd className="font-mono text-sm text-foreground">
                    {formatInr(application.gross_monthly_income_paise)}
                  </dd>
                </div>
                <div>
                  <dt className="text-xs text-muted-foreground">Existing monthly debt</dt>
                  <dd className="font-mono text-sm text-foreground">
                    {formatInr(application.monthly_debt_paise)}
                  </dd>
                </div>
              </dl>
            </CardContent>
          </Card>
        </div>
      </div>
    </div>
  )
}
