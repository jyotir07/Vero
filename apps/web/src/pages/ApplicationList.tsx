import { FilePlus2, Inbox } from 'lucide-react'
import { Link } from 'react-router-dom'

import { formatInr } from '@/api/client'
import { StateBadge } from '@/components/workflow'
import { Alert, AlertDescription } from '@/components/ui/alert'
import { Button } from '@/components/ui/button'
import { Card, CardContent } from '@/components/ui/card'
import { Skeleton } from '@/components/ui/skeleton'
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '@/components/ui/table'
import { useApplicationList } from '@/hooks/useApplication'

export function ApplicationList() {
  const { applications, loading, error } = useApplicationList()

  return (
    <div className="space-y-6">
      <div className="flex items-end justify-between gap-4">
        <div>
          <h1 className="text-2xl font-semibold tracking-tight text-foreground">Applications</h1>
          <p className="text-sm text-muted-foreground">
            Every application the agent has worked on.
          </p>
        </div>
        <Button asChild>
          <Link to="/applications/new">
            <FilePlus2 className="h-4 w-4" aria-hidden />
            New application
          </Link>
        </Button>
      </div>

      {error && (
        <Alert variant="destructive">
          <AlertDescription>{error}</AlertDescription>
        </Alert>
      )}

      {loading ? (
        <div className="space-y-2">
          {[0, 1, 2].map((i) => (
            <Skeleton key={i} className="h-12 w-full" />
          ))}
        </div>
      ) : applications.length === 0 ? (
        <Card>
          <CardContent className="flex flex-col items-center gap-3 py-12 text-center">
            <Inbox className="h-8 w-8 text-muted-foreground" aria-hidden />
            <div>
              <p className="text-sm font-medium text-foreground">No applications yet</p>
              <p className="text-sm text-muted-foreground">
                Create one to watch the workflow run.
              </p>
            </div>
            <Button asChild variant="outline">
              <Link to="/applications/new">Create an application</Link>
            </Button>
          </CardContent>
        </Card>
      ) : (
        <Card className="p-0">
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>Applicant</TableHead>
                <TableHead>Amount</TableHead>
                <TableHead>Tenure</TableHead>
                <TableHead>State</TableHead>
                <TableHead className="text-right">Created</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {applications.map((application) => (
                <TableRow key={application.id}>
                  <TableCell>
                    <Link
                      to={`/applications/${application.id}`}
                      className="font-medium text-foreground underline-offset-4 hover:underline"
                    >
                      {application.applicant_name}
                    </Link>
                  </TableCell>
                  <TableCell className="font-mono text-sm">
                    {formatInr(application.requested_amount_paise)}
                  </TableCell>
                  <TableCell className="font-mono text-sm">
                    {application.tenure_months} mo
                  </TableCell>
                  <TableCell>
                    <StateBadge state={application.state} />
                  </TableCell>
                  <TableCell className="text-right font-mono text-xs text-muted-foreground">
                    {new Date(application.created_at).toLocaleString()}
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </Card>
      )}
    </div>
  )
}
