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
  draft_body: string | null
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

/** Message in the RFQ detail drawer's Messages section */
export interface RfqMessage {
  id: number
  direction: "inbound" | "outbound" | null
  sender: string
  recipients: string | null
  subject: string | null
  body: string
  received_at: string | null
}

/** Carrier bid in the RFQ detail drawer */
export interface CarrierBidItem {
  id: number
  carrier_name: string
  carrier_email: string | null
  rate: number | null
  currency: string | null
  rate_type: string | null
  terms: string | null
  availability: string | null
  notes: string | null
  received_at: string | null
}

/** Allowed state transition for the Current Status section */
export interface AllowedTransition {
  state: string
  label: string
}

/** GET /api/rfqs/{id} — full detail for the RFQ drawer */
export interface RfqDetail {
  id: number
  customer_name: string | null
  customer_email: string | null
  customer_company: string | null
  origin: string | null
  destination: string | null
  equipment_type: string | null
  truck_count: number | null
  commodity: string | null
  weight_lbs: number | null
  pickup_date: string | null
  delivery_date: string | null
  special_requirements: string | null
  state: string
  state_label: string
  confidence_scores: Record<string, number> | null
  outcome: string | null
  quoted_amount: number | null
  closed_at: string | null
  updated_at: string
  created_at: string
  allowed_transitions: AllowedTransition[]
  messages: RfqMessage[]
  timeline: ActivityEvent[]
  carrier_bids: CarrierBidItem[]
  pending_approvals: ApprovalItem[]
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
