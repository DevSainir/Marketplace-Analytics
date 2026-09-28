/**
 * Reading one test through one advertising campaign.
 *
 * The split exists because two campaigns on one card are two different
 * purchases — «Единая» buys mixed placement at a CPM, «CPC» buys clicks — and a
 * campaign that starts or stops in the middle of a test moves the totals in a
 * way that reads exactly like one photo pulling ahead.
 *
 * What is worth pinning is the part that can silently lie: a campaign that was
 * switched off must not be shown as present-but-losing in the laps it never
 * ran. Zero and «not there» are different answers, and only one of them is true.
 */
import { describe, expect, it } from 'vitest'

import { buildTimeline, roundsIn } from '@/modules/abTests/timeline'
import { buildColumns } from '@/modules/abTests/variantColumns'

const UNI = 97455930
const CPC = 97730900
const A = '00000000-0000-7000-8000-00000000000a'
const B = '00000000-0000-7000-8000-00000000000b'

/** One photo's whole-test row, with its per-campaign slices. */
function variant(id, position, campaigns) {
  return {
    variant_id: id,
    position,
    views: campaigns.reduce((sum, row) => sum + row.views, 0),
    clicks: campaigns.reduce((sum, row) => sum + row.clicks, 0),
    click_through: '3.90',
    rounds_played: 4,
    campaigns,
  }
}

/** One turn of the log, and what each campaign earned during it. */
function turn(id, { lap, at, campaigns }) {
  return {
    variant_id: id,
    position: id === A ? 1 : 2,
    is_original: false,
    round_number: lap,
    activated_at: `2026-09-08T${at}:00:00Z`,
    deactivated_at: `2026-09-08T${at}:30:00Z`,
    views: campaigns.reduce((sum, row) => sum + row.views, 0),
    clicks: campaigns.reduce((sum, row) => sum + row.clicks, 0),
    click_through: '4.00',
    campaigns,
  }
}

describe('buildColumns through one campaign', () => {
  it('shows that campaign’s own figures and its own gap to the leader', () => {
    const test = {
      variants: [
        variant(A, 1, [
          {
            campaign_id: UNI,
            views: 2200,
            clicks: 80,
            click_through: '3.64',
            ctr_gap: '0.40',
            ctr_result: '-9.90',
            rounds_played: 4,
          },
          {
            campaign_id: CPC,
            views: 800,
            clicks: 40,
            click_through: '5.00',
            ctr_gap: '0.00',
            ctr_result: '0.00',
            rounds_played: 2,
          },
        ]),
      ],
      history: [],
    }

    const [uni] = buildColumns(test, 0, UNI)
    const [cpc] = buildColumns(test, 0, CPC)

    expect(uni.views).toBe(2200)
    expect(uni.ctr_result).toBe('-9.90')
    // The same photo leads the other campaign — which is the whole reason the
    // gap is recomputed per campaign rather than carried over from the total.
    expect(cpc.views).toBe(800)
    expect(cpc.ctr_result).toBe('0.00')
  })

  it('reads a photo the campaign never served as unmeasured, not as nought percent', () => {
    const test = {
      variants: [variant(A, 1, [{ campaign_id: UNI, views: 100, clicks: 4 }])],
      history: [],
    }

    const [row] = buildColumns(test, 0, CPC)

    expect(row.views).toBe(0)
    expect(row.click_through).toBeNull()
  })

  it('counts a chosen lap out of that campaign’s turns alone', () => {
    const test = {
      variants: [variant(A, 1, [{ campaign_id: UNI, views: 0, clicks: 0 }]), variant(B, 2, [])],
      history: [
        turn(A, {
          lap: 2,
          at: '11',
          campaigns: [
            { campaign_id: UNI, views: 600, clicks: 12 },
            { campaign_id: CPC, views: 400, clicks: 40 },
          ],
        }),
        turn(A, { lap: 1, at: '10', campaigns: [{ campaign_id: UNI, views: 900, clicks: 18 }] }),
      ],
    }

    const [lapTwoUni] = buildColumns(test, 2, UNI)
    const [lapTwoCpc] = buildColumns(test, 2, CPC)

    expect([lapTwoUni.views, lapTwoUni.clicks]).toEqual([600, 12])
    expect([lapTwoCpc.views, lapTwoCpc.clicks]).toEqual([400, 40])
  })
})

describe('the laps one campaign ran for', () => {
  const history = [
    turn(A, { lap: 3, at: '12', campaigns: [{ campaign_id: UNI, views: 500, clicks: 20 }] }),
    turn(A, {
      lap: 2,
      at: '11',
      campaigns: [
        { campaign_id: UNI, views: 500, clicks: 20 },
        { campaign_id: CPC, views: 200, clicks: 10 },
      ],
    }),
    turn(A, {
      lap: 1,
      at: '10',
      campaigns: [
        { campaign_id: UNI, views: 500, clicks: 20 },
        { campaign_id: CPC, views: 200, clicks: 10 },
      ],
    }),
  ]

  it('offers only the laps that campaign was running for', () => {
    expect(roundsIn(history)).toEqual([3, 2, 1])
    expect(roundsIn(history, CPC)).toEqual([2, 1])
  })

  it('draws a line of the turns that campaign measured, not of blanks', () => {
    const line = buildTimeline(history, {
      endsAt: Date.parse('2026-09-08T13:00:00Z'),
      campaignId: CPC,
    })

    expect(line.segments).toHaveLength(2)
    expect(line.segments.map((segment) => segment.round)).toEqual([1, 2])
    expect(line.segments[0].views).toBe(200)
  })
})
