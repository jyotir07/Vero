# System Architecture

```mermaid
flowchart TB
    U[Applicant] --> WEB[React + TypeScript Web App]
    R[Credit Reviewer] --> WEB

    WEB --> API[Node.js / TypeScript API]
    WEB --> VOICE[Voice Gateway]

    API --> WF[Durable Workflow / State Machine]
    WF --> AGENT[AI Agent Orchestrator]

    AGENT --> TOOLS[Validated Tool Layer]
    TOOLS --> DOC[Document Extraction]
    TOOLS --> VERIFY[Income / Credit Verification]
    TOOLS --> RISK[Deterministic Risk & Policy Engine]
    TOOLS --> REVIEW[Human Review Service]

    WF --> DB[(PostgreSQL)]
    API --> DB
    AGENT --> DB
    TOOLS --> DB

    API --> S3[(S3)]
    DOC --> S3

    VOICE --> STT[Speech-to-Text]
    STT --> AGENT
    AGENT --> TTS[Text-to-Speech]
    TTS --> VOICE

    WF --> EVENTS[Audit / Workflow Events]
    EVENTS --> OBS[CloudWatch / Observability]

    API --> AWS[AWS Runtime]
    WF --> AWS
