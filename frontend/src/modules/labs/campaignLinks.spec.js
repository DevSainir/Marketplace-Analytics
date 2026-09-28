import { describe, expect, it } from 'vitest'

import { campaignIdsByDay } from '@/modules/labs/campaignLinks'

describe('campaignIdsByDay', () => {
  it('names each group by whichever of its zones carries the campaign', () => {
    const matrixBase = {
      days: [
        {
          day: '2026-09-25',
          buckets: {
            uni_shelves: { campaign_id: 97455860 },
            manual_catalog: { campaign_id: 97455887 },
            total: {},
          },
        },
      ],
    }

    expect(campaignIdsByDay(matrixBase)).toEqual({
      '2026-09-25': { uni: 97455860, manual_search: 97455887 },
    })
  })

  it('leaves out days and groups no campaign ran, and survives a missing base', () => {
    const matrixBase = { days: [{ day: '2026-09-24', buckets: { uni_search: {} } }] }

    expect(campaignIdsByDay(matrixBase)).toEqual({})
    expect(campaignIdsByDay(null)).toEqual({})
  })
})
