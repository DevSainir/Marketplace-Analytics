import { describe, expect, it } from 'vitest'

import { campaignUrl, sellerCardUrl, storefrontCardUrl } from '@/modules/labs/wbLinks'

describe('wbLinks', () => {
  it('points the storefront link at the card page with no tracking tag', () => {
    expect(storefrontCardUrl(953770957)).toBe(
      'https://www.wildberries.ru/catalog/953770957/detail.aspx',
    )
  })

  it('opens the seller card editor on an existing card', () => {
    expect(sellerCardUrl(953770957)).toBe(
      'https://seller.wildberries.ru/new-goods/card?nmID=953770957&type=EXIST_CARD',
    )
  })

  it('reproduces the campaign link WB itself generates', () => {
    const url = campaignUrl(97455934, { nmId: 1948347102, from: '2026-09-20', to: '2026-09-26' })

    expect(url).toBe(
      'https://cmp.wildberries.ru/campaigns/edit/97455934?advertID=97455934' +
        '&from=2026-09-20T00%3A00%3A00Z&nmId=1948347102&to=2026-09-26T00%3A00%3A00Z',
    )
  })

  it('still opens the campaign when no window or card is known', () => {
    expect(campaignUrl(97455934)).toBe(
      'https://cmp.wildberries.ru/campaigns/edit/97455934?advertID=97455934',
    )
  })
})
