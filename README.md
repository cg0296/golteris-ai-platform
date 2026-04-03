# Operational AI Workflow Platform

An initiative to build an AI-powered operations system that converts natural-language business requests into structured work, tracked workflows, and downstream actions.

## Thesis

Businesses lose time and money translating unstructured communication into spreadsheets, internal records, quotes, and follow-up tasks. The opportunity is to standardize that translation layer.

Instead of relying on one general chatbot, this platform will use:

- focused low-level agents for repeatable tasks
- a central orchestrator to manage flow and state
- deterministic automation for predictable steps
- AI for fuzzy matching, extraction, and exception handling

## Problem

Many operational teams still work out of email and spreadsheets. A request comes in through natural language, someone manually interprets it, asks follow-up questions, builds a sheet, coordinates with suppliers, compares responses, and sends back a final quote or status update.

This creates:

- slow response times
- inbox chaos
- inconsistent handling
- missed details
- lost opportunities
- too much dependence on one person remembering the process

## Initial Use Case

The first target workflow is logistics and carrier procurement.

Example:

1. A customer emails a freight request in natural language.
2. The system extracts shipment details.
3. If required fields are missing, it drafts or sends clarification questions.
4. Once complete, it generates a pricing sheet.
5. The request is sent to multiple carriers.
6. Carrier responses are collected and parsed.
7. Quotes are compared.
8. A final quote is prepared with markup.
9. The workflow is tracked until closed.

## How This Differs From ChatGPT

ChatGPT is primarily a prompt-response assistant.

This platform is intended to be a workflow system that:

- monitors inbound operational communication
- maintains state across multiple messages and steps
- triggers actions automatically
- coordinates tools like email, spreadsheets, and internal records
- uses AI only where ambiguity requires interpretation

The core difference is `conversation` versus `operational execution`.

## Product Principles

- Break work into the smallest repeatable tasks.
- Give each task a clear input and output.
- Keep workflow state explicit.
- Use orchestration to control the process.
- Use AI when reality is messy, not where simple rules are enough.
- Escalate to humans when confidence is low or business risk is high.

## Agent Model

Example low-level agents:

- `Thread Match Agent`
- `Intent Detection Agent`
- `Field Extraction Agent`
- `Missing Fields Agent`
- `Follow-Up Draft Agent`
- `Sheet Generation Agent`
- `Carrier Response Parsing Agent`
- `Quote Comparison Agent`
- `Markup Agent`
- `Customer Quote Agent`
- `Status Update Agent`
- `Escalation Agent`

These should be coordinated by a higher-level orchestrator that knows the current workflow state and decides what runs next.

## Orchestration Model

The platform should support either:

- a custom orchestration layer
- an external automation tool such as `n8n` or `Zapier`

But orchestration logic must remain controlled by the platform's workflow rules and state model.

Suggested state flow:

1. `new_request_received`
2. `needs_clarification`
3. `awaiting_customer_reply`
4. `ready_for_sheet_generation`
5. `sent_to_carriers`
6. `awaiting_carrier_quotes`
7. `quotes_received`
8. `quote_comparison_complete`
9. `final_quote_sent`
10. `won_lost_or_closed`

## MVP

Phase 1 should solve one painful, repeatable task well.

Recommended first scope:

- ingest pasted text or inbound email
- extract key fields into structured JSON
- detect missing information
- draft follow-up questions
- generate a standard spreadsheet or intake sheet
- store workflow state for the request

The goal is to take a task that currently takes hours and reduce it to minutes.

## Near-Term Deliverables

- define the initial request schema
- define required fields for the first workflow
- map low-level agents with inputs and outputs
- design the workflow state machine
- decide where orchestration lives
- build a narrow phase 1 prototype

## Repo Notes

- [a.md](/c:/Users/Curt/Desktop/AGENT_CurtGolden/a.md) contains raw brainstorming and working notes
- `README.md` is the cleaner initiative summary and starting point for execution

## Next Step

The next useful artifact is one of:

1. a phase 1 MVP spec
2. an agent catalog with contracts for each agent
3. a workflow state machine document
4. a technical architecture for the first prototype
