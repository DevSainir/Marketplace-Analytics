/**
 * Links out of the page into WB — the storefront card, the seller's card
 * editor and one advertising campaign. Pure string builders, no fetching.
 *
 * Every link is built from ids alone (nm ID, advert ID), because those are the
 * only parts of WB's URLs that stay put. The formats are copied from links WB
 * itself generates, 2026-09-26:
 *
 *   storefront  /catalog/<nm>/detail.aspx — opened with no query at all; the
 *               `targetUrl=GP` WB appends is a click-source tag, not routing.
 *   seller      /new-goods/card?nmID=<nm>&type=EXIST_CARD — the editor the
 *               "Product cards" list opens.
 *   campaign    /campaigns/edit/<id>?advertID=<id>&from&nmId&to — the path
 *               carries the campaign; `from`/`to` preset its statistics window
 *               and `nmId` the card inside it, so the page opens on the same
 *               days and the same SKU the table is showing.
 */

/** @param {number} nmId */
export function storefrontCardUrl(nmId) {
  return `https://www.wildberries.ru/catalog/${nmId}/detail.aspx`
}

/** @param {number} nmId */
export function sellerCardUrl(nmId) {
  return `https://seller.wildberries.ru/new-goods/card?nmID=${nmId}&type=EXIST_CARD`
}

/**
 * @param {number} advertId WB campaign id
 * @param {{nmId?: number, from?: string, to?: string}} [context] ISO days
 */
export function campaignUrl(advertId, { nmId, from, to } = {}) {
  const params = new URLSearchParams({ advertID: String(advertId) })
  if (from) params.set('from', `${from}T00:00:00Z`)
  if (nmId) params.set('nmId', String(nmId))
  if (to) params.set('to', `${to}T00:00:00Z`)
  return `https://cmp.wildberries.ru/campaigns/edit/${advertId}?${params}`
}
