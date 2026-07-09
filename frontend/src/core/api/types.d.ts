/**
 * Friendly aliases over the auto-generated OpenAPI schema (`schema.d.ts`).
 *
 * Regenerate the schema whenever the backend contract changes:
 *     npm run types:api   (backend must be running on localhost:8000)
 *
 * The runtime code stays plain JS; these types are consumed through JSDoc
 * (`@returns {Promise<import('@/core/api/types').SkuDetailResponse>}`) so the
 * editor and CI can catch contract drift without a TypeScript migration.
 */
import type { components } from './schema'

type Schemas = components['schemas']

// --- Auth ------------------------------------------------------------------
export type UserRead = Schemas['UserRead']
export type TokenPairResponse = Schemas['TokenPairResponse']

// --- Monitoring ------------------------------------------------------------
export type SkuDetailResponse = Schemas['SkuDetailResponse']
export type SkuSummaryListResponse = Schemas['SkuSummaryListResponse']
export type SkuLookupResponse = Schemas['SkuLookupResponse']
export type FunnelResponseSchema = Schemas['FunnelResponseSchema']
export type FunnelTotals = Schemas['FunnelTotals']
export type CampaignAdvertising = Schemas['CampaignAdvertising']
export type StockDetail = Schemas['StockDetail']
