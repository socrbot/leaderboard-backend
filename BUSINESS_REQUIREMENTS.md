# Golf Leaderboard Backend API - Business Requirements

## Document Metadata (Author, Status, Date)

- **Document Title**: Golf Leaderboard Backend API Business Requirements
- **Product**: The Sunday Cup Leaderboard Backend
- **Author**: Russell Girton (Owner), Prepared by Senior Business Analyst
- **Status**: Draft for Stakeholder Review
- **Version**: 2.0
- **Date**: June 23, 2026
- **Primary Audience**: Product, Backend Engineering, Frontend Engineering, QA, DevOps

## Business Context & Objectives

### Business Problem
The organization requires a dependable backend platform to operate multi-league alumni golf tournaments with accurate scoring, reliable draft workflows, and low-latency leaderboard access. Manual reconciliation and fragmented data handling create operational risk, delayed updates, and reduced trust in tournament outcomes.

### Strategic Context
The backend is a Flask API deployed on Cloud Run, backed by Firestore, and integrated with RapidAPI and SportsData.io. It supports real-time and stored scoring, league administration, tournament lifecycle management, and annual championship calculations.

### Core Objectives
- Deliver accurate team scoring and leaderboard results aligned to official source data.
- Support end-to-end tournament operations from setup through completion.
- Enforce league-based access controls for V2 operations while preserving required public read paths.
- Minimize third-party API consumption through caching, persistence, and quota controls.
- Provide operational reliability during active tournament windows.

### Timeline and Budget Constraints
- Delivery occurs during active golf season with frequent incremental releases.
- Cost controls require quota-aware API usage and efficient serverless scaling.
- Changes should prioritize high business impact with minimal added infrastructure overhead.

## Target Personas / Users

- **League Administrator**
  - Creates leagues and tournaments, manages members, and controls draft operations.
  - Requires predictable workflows, secure admin actions, and clear system status.

- **Tournament Participant**
  - Consumes leaderboard and team results through frontend clients.
  - Requires timely, accurate scoring and stable endpoint behavior.

- **Super Admin / Operator**
  - Handles exceptional states, data corrections, and production oversight.
  - Requires elevated controls and transparent diagnostics.

- **Engineering and DevOps Team**
  - Owns backend delivery, performance, monitoring, and incident response.
  - Requires maintainable architecture and auditable deployment flow.

## In-Scope & Out-of-Scope

### In-Scope
- Tournament CRUD and lifecycle state management.
- Team assignment, draft status management, and odds lock workflows.
- Live and persisted leaderboard score computation and retrieval.
- Annual championship aggregation for eligible completed tournaments.
- League and membership-aware API behavior for protected operations.
- API quota management, caching, and monitoring support endpoints.

### Out-of-Scope
- Native mobile client development.
- Replacement of third-party data providers.
- Payment, billing, or monetization features.
- Full data warehouse and long-term BI analytics platform.
- Major infrastructure migration away from Cloud Run and Firestore.

## Functional Requirements (Format as "The system shall [action]...")

- The system shall provide tournament listing and filtering by year and league context.
- The system shall create tournaments with required metadata and default workflow flags.
- The system shall return tournament details, including draft and lifecycle state indicators.
- The system shall support updating tournament team assignments with exactly four golfers per team.
- The system shall compute team scores using the best 3 of 4 golfer scores per round.
- The system shall apply CUT penalties for missed rounds based on worst non-cut score plus one stroke.
- The system shall parse and normalize external score formats including E, +N, and -N values.
- The system shall persist calculated tournament scores for completed or stable states to Firestore.
- The system shall return stored score snapshots when source data has not materially changed.
- The system shall expose draft lifecycle endpoints for start, lock odds, and complete transitions.
- The system shall provide draft status endpoints used by frontend workflow gating.
- The system shall retrieve and normalize player odds for draft workflows.
- The system shall support global team CRUD and year-based team reuse operations.
- The system shall synchronize tournament teams from global teams when requested.
- The system shall calculate annual championship standings using cumulative stroke scoring.
- The system shall include only eligible tournaments in annual standings based on completion and participation flags.
- The system shall enforce role and league authorization checks on protected mutating endpoints.
- The system shall support required public read endpoints for compatible frontend views.
- The system shall expose rate-limit status and quota consumption for operational visibility.
- The system shall provide health and diagnostic endpoints for runtime monitoring and troubleshooting.

## Non-Functional Requirements (Performance, Security, Compliance)

### Performance
- The system shall return cached read responses within 500 ms at p95.
- The system shall return non-cached leaderboard responses within 2 seconds at p95 under normal provider latency.
- The system shall complete team score calculations for standard tournament sizes within 1 second at p95.
- The system shall maintain high cache effectiveness for repeated leaderboard reads during active play.

### Security
- The system shall require authenticated identity tokens for protected V2 user and admin operations.
- The system shall enforce league-scoped authorization for league and tournament mutating actions.
- The system shall use HTTPS for all traffic and never expose provider secrets in responses.
- The system shall validate and sanitize request inputs before persistence or external calls.
- The system shall restrict CORS to approved origins for production, staging, and local development.

### Compliance and Governance
- The system shall use environment-specific deployment workflows and branch gating for production safety.
- The system shall maintain auditable logs for API errors, critical transitions, and external API failures.
- The system shall manage secrets via secure secret storage and service account access controls.
- The system shall preserve operational controls for public service endpoints while enforcing app-layer auth.

## Key Success Metrics (KPIs)

- **Leaderboard Accuracy Rate**: 100% parity with official source or approved stored results.
- **Cached Read Latency (p95)**: <= 500 ms.
- **Fresh Leaderboard Latency (p95)**: <= 2,000 ms.
- **API Availability**: >= 99.5% monthly uptime.
- **RapidAPI Daily Quota Compliance**: <= configured daily threshold on standard operating days.
- **Score Persistence Reliability**: >= 99.9% successful write operations for score snapshots.
- **Draft Workflow Completion Rate**: >= 98% of drafts move from started to completed without manual data repair.
- **Incident Recovery Time**: < 30 minutes median for critical backend regressions during tournament windows.

## Assumptions & Risks

### Assumptions
- External data providers remain available and schema-compatible with current adapters.
- Firestore and Cloud Run operate within expected service-level reliability.
- League admins follow defined workflow sequencing for draft and tournament operations.
- Frontend clients consume endpoints according to published API contracts.

### Risks
- **Provider Data Risk**: Upstream feed inconsistencies can temporarily impact score correctness.
- **Quota Risk**: Third-party API limits can reduce freshness during high-traffic periods.
- **Authorization Regression Risk**: Route-level auth changes can unintentionally break V1 or V2 consumer behavior.
- **Data Integrity Risk**: Incomplete or malformed team assignments can block accurate scoring.
- **Operational Risk**: In-season hotfixes and rapid releases can increase deployment error probability.
- **Dependency Risk**: Secret misconfiguration or service-account drift can disrupt production integrations.
