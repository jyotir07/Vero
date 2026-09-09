# Vero (Latin: truth/verification)
An AI Credit Underwriting Agent

## Project goal

Build a production-style, end-to-end AI system that automates a realistic credit underwriting workflow while keeping the decision process **stateful, auditable, deterministic where it matters, and human-controlled when risk is high**.

The project is intentionally designed to demonstrate the exact engineering profile of a Full Stack AI Engineer: React + TypeScript, backend APIs, LLM agents, state machines, voice AI, AWS deployment, observability, and reliable workflow execution.

> **Core idea:** the LLM should reason and choose actions, but it should not be allowed to bypass the workflow, business rules, permissions, or audit trail.

---

# 1. What the product should do

A user submits a loan/credit application through a web application.

The system then takes the application through a stateful workflow:

```text
Application Received
        ↓
Document Check
        ↓
Income Verification
        ↓
Credit Analysis
        ↓
Risk Assessment
        ↓
 ┌───────────────┐
 │ Human Review? │
 └───────┬───────┘
     Yes ↓   ↓ No
    Human   Decision
    Review     ↓
       └──────→
               ↓
        Approved / Rejected
```

The AI agent should:

- inspect application information
- identify missing information
- extract structured information from documents
- call verification/calculation tools
- analyze financial information
- explain why a case needs escalation
- recommend an outcome
- communicate with the applicant through text or voice
- resume a workflow after human review
- maintain an auditable history of every important action

The system should **not** pretend to make real lending decisions or connect to real financial institutions. Use synthetic applicant data and clearly label the project as a technical demonstration.

---

# 2. Primary user experiences

## Applicant

The applicant can:

1. Create an application.
2. Enter basic financial information.
3. Upload synthetic documents.
4. See application progress.
5. Receive requests for missing information.
6. Interact with the AI agent through chat.
7. Optionally use a voice agent.
8. Receive a simulated final outcome and explanation.

## Credit analyst / reviewer

A reviewer can:

1. See applications requiring attention.
2. Inspect the complete workflow timeline.
3. Review extracted document data.
4. See agent reasoning summaries and tool calls.
5. Approve, reject, or request more information.
6. Override an AI recommendation.
7. Add a review note.
8. Resume the workflow after a decision.

The reviewer should always be able to see **what the agent did and why the case reached human review**.

---

# 3. The state machine

This is the heart of the project.

Each application has a durable workflow state.

Suggested states:

```text
RECEIVED
DOCUMENT_CHECK
INCOME_VERIFICATION
CREDIT_ANALYSIS
RISK_ASSESSMENT
HUMAN_REVIEW
DECISION
APPROVED
REJECTED
MORE_INFORMATION_REQUIRED
FAILED
```

### Example transition

```text
DOCUMENT_CHECK
      |
      +-- documents complete --> INCOME_VERIFICATION
      |
      +-- missing documents --> MORE_INFORMATION_REQUIRED
      |
      +-- extraction failure --> FAILED
```

The state machine must enforce valid transitions.

The LLM cannot arbitrarily change:

```text
DOCUMENT_CHECK → APPROVED
```

Instead:

```text
LLM proposes action
        ↓
Backend validates action
        ↓
State machine checks transition
        ↓
Tool executes
        ↓
Database records event
        ↓
Next state
```

This is one of the most important architectural decisions in the project.

---

# 4. AI agent design

Use an agentic architecture where the model can select tools, but all side effects happen through controlled backend functions.

Possible tools:

- `extract_document`
- `check_required_documents`
- `calculate_dti`
- `calculate_affordability`
- `verify_income`
- `run_credit_check`
- `evaluate_policy`
- `request_information`
- `create_human_review`
- `get_application`
- `update_application_status`

The agent should return structured actions rather than arbitrary text.

Example:

```json
{
  "action": "REQUEST_DOCUMENT",
  "document_type": "BANK_STATEMENT",
  "reason": "Required document is missing"
}
```

The backend validates the action before execution.

---

# 5. Credit/risk simulation

Use synthetic data to create a realistic workflow.

Useful derived metrics:

- debt-to-income ratio
- monthly disposable income
- income stability
- existing obligations
- requested loan amount
- loan-to-income ratio
- simulated credit score
- document completeness
- verification confidence

Example:

```text
Monthly income:          ₹150,000
Monthly debt:             ₹35,000
Requested loan:          ₹800,000
Synthetic credit score:       742
DTI:                         23.3%
Document completeness:        100%
```

The system can use deterministic policy rules alongside the LLM.

For example:

```text
if documents_missing:
    request_more_information()

elif verification_failed:
    escalate_to_human()

elif policy_flags:
    human_review()

else:
    generate_recommendation()
```

The LLM should **interpret and orchestrate**, while deterministic code handles critical business rules.

---

# 6. Human-in-the-loop workflow

Human review is a first-class part of the system.

Cases should be escalated when:

- verification fails
- required information conflicts
- confidence is low
- policy rules are triggered
- the agent encounters an unsupported situation
- a reviewer is required by the simulated policy

Example:

```text
AI Agent
   ↓
Risk Assessment
   ↓
Policy / confidence check
   ↓
Human Review
   ↓
Reviewer decision
   ↓
Workflow resumes
```

The reviewer should be able to approve or reject the recommendation and leave an explanation.

---

# 7. Voice agent

Build a voice interface for applicant communication.

Example flow:

```text
Applicant speaks
      ↓
Speech-to-text
      ↓
Conversation / workflow agent
      ↓
Tool calls if required
      ↓
Text response
      ↓
Text-to-speech
      ↓
Applicant hears response
```

Useful voice interactions:

- "What's the status of my application?"
- "What document am I missing?"
- "Why do you need my bank statement?"
- "Can I update my income?"
- "I want to speak to a human."

The voice system should optimize for latency.

Track:

- speech-to-text latency
- LLM latency
- tool latency
- text-to-speech latency
- total turn latency

Target a responsive conversational experience and document the measured latency rather than claiming an arbitrary benchmark.

---

# 8. Latency engineering

Latency should be treated as a product metric.

Instrument every stage:

```text
Audio input
   ↓
STT        300ms
   ↓
LLM       700ms
   ↓
Tool      150ms
   ↓
TTS       300ms
   ↓
Total    1450ms
```

The actual values should come from telemetry.

Possible optimizations:

- streaming STT
- streaming TTS
- smaller/faster models for simple classification
- parallel tool calls
- cached application context
- reduced prompt size
- structured outputs
- asynchronous background work
- avoiding unnecessary agent turns

A strong README should show a before/after latency measurement if optimization work is performed.

---

# 9. Frontend

Use **React + TypeScript**.

Recommended screens:

### Applicant dashboard

- application status
- workflow progress
- document checklist
- outstanding actions
- AI chat
- voice interaction

### Reviewer dashboard

- applications queue
- risk/priority indicators
- application details
- workflow state
- agent activity
- extracted document information
- tool calls
- review controls
- audit timeline

### Workflow timeline

Example:

```text
09:41  Application received
09:42  Documents extracted
09:42  Income verified
09:43  Credit analysis completed
09:43  Policy exception detected
09:43  Sent to human review
10:17  Reviewer approved
10:17  Final decision generated
```

This timeline is valuable proof that the system is genuinely stateful.

---

# 10. Backend

Recommended stack:

- Node.js + TypeScript for APIs and orchestration
- FastAPI can be used for Python-specific AI/document/speech services
- PostgreSQL for durable application state
- Redis where useful for caching/queues
- object storage for synthetic documents
- WebSockets/SSE for live workflow updates

Suggested API surface:

```text
POST   /applications
GET    /applications/:id
POST   /applications/:id/documents
GET    /applications/:id/events
POST   /applications/:id/messages
POST   /applications/:id/voice
POST   /applications/:id/review
POST   /applications/:id/resume
```

Keep business logic out of React and keep LLM calls behind backend interfaces.

---

# 11. Data model

Core entities:

```text
Application
Document
WorkflowRun
WorkflowEvent
AgentAction
ToolCall
RiskAssessment
HumanReview
Conversation
AuditLog
```

Every significant workflow mutation should generate an immutable event.

Example:

```json
{
  "application_id": "app_123",
  "event": "STATE_CHANGED",
  "from": "RISK_ASSESSMENT",
  "to": "HUMAN_REVIEW",
  "actor": "agent",
  "timestamp": "..."
}
```

This creates an audit trail and makes debugging easier.

---

# 12. Reliability requirements

The project should demonstrate that AI systems can fail without corrupting the workflow.

Handle:

- model timeout
- malformed structured output
- tool failure
- duplicate requests
- document extraction failure
- network failure
- invalid state transitions
- human review delays
- agent retry loops

Important properties:

### Idempotency

Retrying a workflow step should not accidentally perform a side effect twice.

### Durable state

Restarting the backend should not lose an application's progress.

### Explicit transitions

Only valid state transitions are allowed.

### Timeouts

Every external dependency should have a timeout.

### Retries

Retries should be bounded and observable.

### Auditability

Important actions should be recorded.

---

# 13. AWS deployment

A reasonable architecture:

```text
CloudFront
    ↓
Frontend
    ↓
API / Load Balancer
    ↓
Backend services
    ↓
PostgreSQL
    ↓
Object storage

Background workers
    ↓
Queues
    ↓
AI / document / voice services
```

Potential AWS services:

- ECS/Fargate or Lambda
- Application Load Balancer
- RDS PostgreSQL
- S3
- SQS
- CloudFront
- CloudWatch
- Secrets Manager
- IAM

Don't use AWS services merely for the sake of the resume. Explain why each service is used.

---

# 14. Observability

Build a small internal observability page or expose useful metrics.

Track:

### Workflow

- applications processed
- average processing time
- human escalation rate
- workflow failure rate
- state transition counts

### AI

- model latency
- token usage
- tool-call count
- malformed outputs
- retry count

### Voice

- STT latency
- LLM latency
- TTS latency
- end-to-end latency

### Reliability

- failed jobs
- retry rate
- queue depth
- API errors

This turns the project from a demo into something that looks like an actual production system.

---

# 15. Security and responsible AI

Even though the project uses synthetic data, demonstrate good practices.

- never commit secrets
- use environment variables / secret management
- validate uploads
- authenticate reviewer actions
- authorize state-changing operations
- avoid exposing internal prompts
- log important actions without leaking sensitive data
- clearly separate AI recommendations from final human decisions
- use synthetic financial identities and documents

The project should explicitly state that it is a **simulation and not a real credit decisioning system**.

---

# 16. Recommended repository structure

```text
ai-credit-agent/
│
├── apps/
│   ├── web/                  # React + TypeScript
│   └── api/                  # Node.js API
│
├── services/
│   ├── agent/                # Agent orchestration
│   ├── document-ai/          # Document extraction
│   └── voice/                # STT / TTS
│
├── packages/
│   ├── state-machine/        # Workflow definitions
│   ├── domain/               # Shared types/business models
│   └── ai/                   # LLM/tool abstractions
│
├── infrastructure/
│   └── aws/                  # IaC / deployment
│
├── docs/
│   ├── architecture.md
│   ├── decisions.md
│   └── latency.md
│
└── README.md
```

The exact structure can be simplified if it makes the project easier to maintain.

---

# 17. MVP scope

Do not overbuild the first version.

### Phase 1: Core workflow

- React dashboard
- backend API
- PostgreSQL
- state machine
- synthetic applications
- document upload
- basic agent
- deterministic credit/risk calculations

### Phase 2: Reliability

- durable workflow state
- tool calling
- audit events
- retries
- human review
- workflow resume

### Phase 3: Voice

- STT
- voice agent
- TTS
- latency instrumentation
- streaming where practical

### Phase 4: Productionization

- AWS deployment
- CI/CD
- observability
- error handling
- authentication
- polished UI

---

# 18. What the final demo should show

A 2-3 minute demo should tell one complete story.

### Scene 1: Application

Create a synthetic applicant and submit an application.

### Scene 2: Agent processing

Show the workflow progressing automatically.

### Scene 3: Missing information

Intentionally provide an incomplete application.

The agent identifies the missing document and requests it.

### Scene 4: Risk assessment

Show deterministic calculations and the agent's recommendation.

### Scene 5: Human escalation

Trigger a policy/confidence exception.

Show the case entering human review.

### Scene 6: Reviewer

Approve/reject the case and leave a note.

### Scene 7: Resume

Show the state machine resuming and producing the final simulated outcome.

### Scene 8: Voice

Ask the voice agent for application status and demonstrate the response.

### Scene 9: Observability

Show latency, workflow events, tool calls, and audit history.

This single demo communicates most of the skills in the job description.

---

# 19. Proof-of-work package

The project should be presented as an engineering artifact, not simply as an AI demo.

Include:

1. **GitHub repository**
2. **Live deployment**
3. **2-3 minute demo video**
4. **Architecture diagram**
5. **Short technical writeup**
6. **Latency measurements**
7. **Example workflow traces**
8. **Tests for state transitions and critical business rules**

The README should answer:

> What did you build?

> Why is the architecture designed this way?

> What happens when the AI fails?

> How is state persisted?

> How does human review work?

> How did you reduce latency?

> How is the system deployed?

> What would you change at 10x scale?

---

# 20. Interview talking points

This project should give you strong answers to questions such as:

### "Why use a state machine?"

Because an LLM is probabilistic, while financial workflows need explicit states, valid transitions, persistence, retries, and auditability.

### "Why not let the agent directly update the database?"

Because model output should not have unrestricted side effects. The agent proposes an action, while validated backend tools execute it.

### "How do you handle failures?"

Persist state and events, make side effects idempotent, use bounded retries, enforce timeouts, and route unrecoverable cases to human review.

### "How did you optimize voice latency?"

Measure each stage independently, then reduce unnecessary model turns, use streaming where possible, parallelize independent work, and choose appropriate models for each task.

### "Where should AI be used and where shouldn't it?"

Use AI for interpretation, extraction, conversation, and orchestration. Use deterministic code for critical calculations, permissions, state transitions, and policy enforcement.

---

# 21. What makes this project compelling for this role

This project deliberately demonstrates:

**Frontend**

React + TypeScript + real product UI

**Backend**

Node.js / FastAPI + APIs + persistence

**AI**

LLMs + structured outputs + tool calling + agents

**Agentic systems**

Multi-step tool-driven workflow

**State machines**

Durable explicit workflow state

**Voice**

STT + LLM + TTS + latency measurement

**Fintech**

Synthetic credit/underwriting workflow

**AWS**

Cloud deployment + managed infrastructure

**Production engineering**

Retries + idempotency + observability + auditability

**Ownership**

A complete product built end-to-end rather than an isolated model demo

---

# 22. North-star principle

The project should communicate one engineering philosophy:

> **Use AI where intelligence is useful, and deterministic software where correctness is mandatory.**

That is the core idea that makes this more credible than a generic "AI agent" project and makes it directly relevant to an early-stage AI fintech building reliable banking workflows.
