/**
 * types/api.ts — TypeScript interfaces for Golteris API responses.
 *
 * These mirror the JSON shapes returned by backend/api/dashboard.py.
 * Field names match the backend serializers exactly.
 */

/** GET /api/dashboard/summary */
export interface DashboardSummary {
  needs_review: number
  active_rfqs: number
  quotes_received_today: number
  time_saved_minutes: number
}

/** Single RFQ in GET /api/rfqs response */
export interface RfqSummary {
  id: number
  customer_name: string | null
  customer_company: string | null
  origin: string | null
  destination: string | null
  equipment_type: string | null
  truck_count: number | null
  state: string
  state_label: string
  updated_at: string
  created_at: string
}

/** GET /api/rfqs response envelope */
export interface RfqListResponse {
  rfqs: RfqSummary[]
  total: number
  limit: number
  offset: number
}

/** Single approval in GET /api/approvals response */
export interface ApprovalItem {
  id: number
  rfq_id: number
  approval_type: string
  draft_subject: string | null
  draft_recipient: string | null
  reason: string | null
  status: string
  created_at: string
  rfq: {
    id: number
    customer_name: string | null
    origin: string | null
    destination: string | null
  } | null
}

/** GET /api/approvals response envelope */
export interface ApprovalListResponse {
  approvals: ApprovalItem[]
  total: number
}

/** Single event in GET /api/activity/recent response */
export interface ActivityEvent {
  id: number
  rfq_id: number | null
  event_type: string
  actor: string
  description: string
  created_at: string
}

/** GET /api/activity/recent response envelope */
export interface ActivityResponse {
  events: ActivityEvent[]
}

/** GET /api/approvals/{id} — full detail for the approval modal */
export interface ApprovalDetail {
  id: number
  rfq_id: number
  approval_type: string
  draft_body: string
  draft_subject: string | null
  draft_recipient: string | null
  reason: string | null
  status: string
  created_at: string
  rfq: {
    id: number
    customer_name: string | null
    customer_company: string | null
    origin: string | null
    destination: string | null
  } | null
  original_message: {
    sender: string
    subject: string | null
    body: string
    received_at: string | null
  } | null
}
