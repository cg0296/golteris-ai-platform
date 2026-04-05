# Current State Architecture — Freight Quote Process

## Overview

The current architecture is **email-centric and human-bottlenecked**. The broker and their inbox are a single black box — the only integration point for all communication, data, and decisions. Everything funnels through one person.

---

## Hub & Spoke — Everything Through the Broker

```mermaid
flowchart TD
    CUS1["Customer A"]:::cust <-->|"RFQ / Quote"| BROKER
    CUS2["Customer B"]:::cust <-->|"RFQ / Quote"| BROKER
    CUS3["Customer C"]:::cust <-->|"RFQ / Quote"| BROKER

    BROKER["Broker\n\nEmail + Manual Process\n(Black Box)"]:::blackbox

    BROKER <-->|"RFQ / Bid"| CAR1["Carrier A"]:::carrier
    BROKER <-->|"RFQ / Bid"| CAR2["Carrier B"]:::carrier
    BROKER <-->|"RFQ / Bid"| CAR3["Carrier C"]:::carrier

    classDef cust fill:#0ea5e9,stroke:#0284c7,color:#fff
    classDef carrier fill:#f59e0b,stroke:#d97706,color:#fff
    classDef blackbox fill:#1e1e2e,stroke:#8b5cf6,color:#e2e8f0,stroke-width:3px
```

```
                    Customer A
                        │
                   RFQ ↓↑ Quote
                        │
    Customer B ←──→ ┌────────────────────────┐ ←──→ Carrier A
                    │                        │
    RFQ / Quote     │       BROKER           │     RFQ / Bid
                    │                        │
    Customer C ←──→ │  Email + Manual Process│ ←──→ Carrier B
                    │      (Black Box)       │
                    └────────────────────────┘ ←──→ Carrier C
```

---

## What's Inside the Black Box

The broker manually handles all of the following using only email and spreadsheets:

| Input | Manual Process | Output |
|-------|---------------|--------|
| Customer RFQ email | Read, interpret, check completeness | Follow-up email or structured spreadsheet |
| Structured spreadsheet | Copy into emails for each carrier | Carrier RFQ emails |
| Carrier bid emails | Read each, extract pricing, enter into spreadsheet | Comparison spreadsheet |
| Comparison spreadsheet | Evaluate, negotiate, select, apply markup | Final quote |
| Final quote | Compose email | Quote email to customer |

---

## Key Problems

| Problem | Impact |
|---------|--------|
| **Single point of failure** | One person, one inbox. Broker unavailable = everything stops. |
| **Unstructured data** | All information lives in email threads and manually-built spreadsheets. No system of record. |
| **No audit trail** | Can't trace how a quote was built or why a carrier was selected. |
| **Serial throughput** | One quote at a time. Scaling means hiring more brokers. |
| **Error-prone** | Every data transfer is manual copy/paste. Typos, missed fields, wrong versions. |

---

## Key Insight

> The broker's inbox is not an architecture — it's the **absence** of one. Email is being used as a database, a workflow engine, a communication bus, and a filing system all at once. The broker is the only "integration layer" connecting customers, carriers, and data.
