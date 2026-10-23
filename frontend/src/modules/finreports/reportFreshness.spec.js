/**
 * The freshness line's wording rules.
 *
 * This line exists because a P&L that stops nine days ago is usually a quiet
 * week and occasionally a dead harvester, and the page used to show the two
 * identically. So the assertions here are mostly about what it must NOT say: a
 * check that failed is never "nothing new", and a stale check never reads
 * as reassurance.
 */
import { describe, expect, it } from 'vitest'

import {
  describeFreshness,
  formatCheckDay,
  formatPeriod,
} from '@/modules/finreports/reportFreshness'

const NOW = new Date('2026-08-18T09:00:00Z')

/** The newest weekly report on file. */
function report(fields = {}) {
  return {
    report_id: 969371534,
    date_from: '2026-08-10',
    date_to: '2026-08-16',
    harvested_at: '2026-08-18T06:14:00Z',
    ...fields,
  }
}

/** A recorded verdict, empty by default — the quiet-week case. */
function check(fields = {}) {
  return {
    outcome: 'wb_empty',
    checked_at: '2026-08-18T08:48:00Z',
    probe_from: '2026-08-17',
    probe_to: '2026-08-17',
    ...fields,
  }
}

describe('formatPeriod', () => {
  it('writes a week inside one month as one range, day first', () => {
    expect(formatPeriod(report())).toBe('10–16 Aug')
  })

  it('names both months when the week straddles two', () => {
    expect(formatPeriod(report({ date_from: '2026-07-28', date_to: '2026-08-03' }))).toBe(
      '28 Jul – 3 Aug',
    )
  })

  it('does not shift a calendar date into another day', () => {
    // A report's period is a calendar day, not an instant. Parsed through
    // `new Date('2026-08-16')` it is midnight UTC and prints as the 15th for
    // every reader west of Greenwich.
    expect(formatPeriod(report({ date_from: '2026-08-16', date_to: '2026-08-16' }))).toBe(
      '16–16 Aug',
    )
  })

  it('says which endpoint it has when WB stated only one', () => {
    expect(formatPeriod(report({ date_from: null }))).toBe('through 16 Aug')
  })

  it('is empty for a header WB stated no period for', () => {
    expect(formatPeriod(report({ date_from: null, date_to: null }))).toBe('')
  })
})

describe('formatCheckDay', () => {
  it('names the local day of the last check', () => {
    expect(formatCheckDay('2026-08-15T09:00:00Z')).toMatch(/^1[45] Aug$/)
  })

  it('is empty for something that is not an instant', () => {
    expect(formatCheckDay('some time')).toBe('')
  })
})

describe('describeFreshness', () => {
  it('names the last weekly report and how far the daily ones reach', () => {
    // The statement runs past the weekly report on WB's per-day reports. The
    // weekly period alone over figures that run further reads as "how, then?".
    const line = describeFreshness(
      {
        latest_report: report(),
        last_check: check({ outcome: 'up_to_date' }),
        provisional_through: '2026-08-17',
      },
      NOW,
    )

    expect(line.text).toBe('Latest WB weekly report: 10–16 Aug · daily through 17 Aug')
    expect(line.tone).toBe('muted')
  })

  it('says nothing about daily reports that do not reach past the weekly one', () => {
    const line = describeFreshness(
      { latest_report: report(), last_check: check({ outcome: 'up_to_date' }) },
      NOW,
    )

    expect(line.text).toBe('Latest WB weekly report: 10–16 Aug')
  })

  it('does not say how long ago a fresh check ran', () => {
    // "checked 12 min ago" on every load was noise; only a stale check
    // earns its date (below).
    const line = describeFreshness({ latest_report: report(), last_check: check() }, NOW)

    expect(line.text).not.toMatch(/check/i)
    expect(line.text).not.toContain('uploaded')
  })

  it('names the first daily report WB has not published, once that day is over', () => {
    const line = describeFreshness(
      {
        latest_report: report(),
        last_check: check(),
        provisional_through: '2026-08-16',
      },
      new Date('2026-08-18T09:00:00'),
    )

    expect(line.text).toContain("WB hasn't published the daily report for 17 Aug yet")
    expect(line.tone).toBe('muted')
  })

  it('does not call WB late for a day that is not over yet', () => {
    const line = describeFreshness(
      { latest_report: report(), last_check: check(), provisional_through: '2026-08-17' },
      new Date('2026-08-18T09:00:00'),
    )

    expect(line.text).toContain("WB hasn't published new reports yet")
    expect(line.text).not.toContain('18 Aug')
  })

  it('says a new report is loading only while it is', () => {
    // The walk records "wb_has_new" again once it succeeds, so the verdict
    // outlives the run; after it, the report is on the page, not "loading".
    const state = { latest_report: report(), last_check: check({ outcome: 'wb_has_new' }) }

    expect(describeFreshness({ ...state, running: true }, NOW).text).toContain(
      'WB published a new report — loading',
    )
    expect(describeFreshness({ ...state, running: false }, NOW).text).toBe(
      'Latest WB weekly report: 10–16 Aug',
    )
  })

  it('never phrases a failed check as "nothing new"', () => {
    // The rule the whole feature turns on: WB not answering is an unanswered
    // question. Reporting silence as reassurance is the failure this line was
    // added to prevent, not one it may reintroduce.
    const line = describeFreshness(
      { latest_report: report(), last_check: check({ outcome: 'probe_failed' }) },
      NOW,
    )

    expect(line.text).not.toMatch(/hasn't published/)
    expect(line.text).toContain("WB didn't answer — newer reports may exist")
    expect(line.tone).toBe('warning')
  })

  it('warns once nobody has asked in over a day, and says when it last did', () => {
    // A confident "nothing new" from yesterday is what a dead harvester
    // looks like — the same words as a healthy quiet week, and only the age
    // separates them.
    const line = describeFreshness(
      {
        latest_report: report(),
        last_check: check({ outcome: 'up_to_date', checked_at: '2026-08-16T09:00:00Z' }),
      },
      NOW,
    )

    expect(line.text).toMatch(/last WB check: 1[56] Aug$/)
    expect(line.tone).toBe('warning')
  })

  it('admits it does not know when no check is recorded', () => {
    // Redis did not answer, the record expired, or it came back in an unknown
    // shape: all three arrive as null, and none may read as "nothing new".
    const line = describeFreshness({ latest_report: report(), last_check: null }, NOW)

    expect(line.text).toContain('Last WB check unknown — data may be incomplete')
    expect(line.tone).toBe('warning')
  })

  it('does not narrate an outcome this build does not know', () => {
    const line = describeFreshness(
      { latest_report: report(), last_check: check({ outcome: 'something_new' }) },
      NOW,
    )

    expect(line.text).toBe('Latest WB weekly report: 10–16 Aug')
  })

  it('says only that it is loading on a workspace with no reports yet', () => {
    const line = describeFreshness(
      { latest_report: null, last_check: check({ outcome: 'never_harvested' }) },
      NOW,
    )

    expect(line.text).toBe('Loading reports from WB…')
  })

  it('says the workspace has no reports rather than inventing a period', () => {
    const line = describeFreshness(
      { latest_report: null, last_check: check({ outcome: 'probe_failed' }) },
      NOW,
    )

    expect(line.text).toContain('No WB reports yet')
  })

  it('renders nothing when the state could not be fetched', () => {
    // The statement has its own error channel; a footnote must not shout over
    // what it annotates.
    expect(describeFreshness(null, NOW)).toBeNull()
    expect(describeFreshness({ latest_report: null, last_check: null }, NOW)).toBeNull()
  })
})

describe('a WB rate block', () => {
  it('is never worded as "nothing new"', () => {
    const line = describeFreshness(
      {
        latest_report: {
          report_id: 989286628,
          date_from: '2026-09-07',
          date_to: '2026-09-13',
          harvested_at: '2026-09-14T09:54:14Z',
        },
        last_check: { outcome: 'rate_blocked', checked_at: '2026-09-17T10:00:00Z' },
        running: false,
      },
      new Date('2026-09-17T10:05:00Z'),
    )

    expect(line.text).toContain("WB is rate-limiting requests — we'll load once it lifts")
    expect(line.text).not.toContain("hasn't published")
  })

  it('is a warning, because the statement may be short a week', () => {
    const line = describeFreshness(
      {
        latest_report: null,
        last_check: { outcome: 'rate_blocked', checked_at: '2026-09-17T10:00:00Z' },
        running: false,
      },
      new Date('2026-09-17T10:05:00Z'),
    )

    expect(line.tone).toBe('warning')
  })
})

describe('describeFreshness — a report WB has formed and not yet served', () => {
  // 12 Oct 2026: the weekly report for 5–11 Oct was on WB's site by 08:00 and
  // absent from the API at 08:05. The seller sees it there; the line says why
  // it is not here yet instead of "WB hasn't published".
  const MONDAY = new Date('2026-10-12T05:10:00Z')
  const state = (fields = {}) => ({
    latest_report: report({ date_from: '2026-10-01', date_to: '2026-10-04' }),
    provisional_through: '2026-10-11',
    awaited_report: { date_from: '2026-10-05', date_to: '2026-10-11' },
    last_check: check({ outcome: 'up_to_date', checked_at: '2026-10-12T04:55:00Z' }),
    ...fields,
  })

  it('names the period on a second line, with the reason behind ⓘ', () => {
    const line = describeFreshness(state(), MONDAY)

    expect(line.text).toBe('Latest WB weekly report: 1–4 Oct · daily through 11 Oct')
    expect(line.notes).toEqual([
      {
        text: 'Report for 5–11 Oct is ready, waiting for the API',
        hint: expect.stringContaining('usually a few hours on'),
      },
    ])
    expect(line.tone).toBe('muted')
  })

  it('replaces "WB hasn\'t published", which the seller can see is untrue', () => {
    const line = describeFreshness(
      state({ last_check: check({ outcome: 'wb_empty', checked_at: '2026-10-12T04:55:00Z' }) }),
      MONDAY,
    )

    expect(line.text).not.toContain("hasn't published")
    expect(line.notes[0].text).toBe('Report for 5–11 Oct is ready, waiting for the API')
  })

  it('gives way to "loading" once the API has served it', () => {
    const line = describeFreshness(
      state({ running: true, last_check: check({ outcome: 'wb_has_new' }) }),
      MONDAY,
    )

    expect(line.text).toContain('WB published a new report — loading')
    expect(line.notes).toEqual([])
  })

  it('keeps an unanswered check visible beside it — waiting is not reassurance', () => {
    const line = describeFreshness(
      state({ last_check: check({ outcome: 'probe_failed', checked_at: '2026-10-12T04:55:00Z' }) }),
      MONDAY,
    )

    expect(line.text).toContain("WB didn't answer — newer reports may exist")
    expect(line.notes[0].text).toContain('waiting for the API')
    expect(line.tone).toBe('warning')
  })

  it('has no second line when there is nothing to wait for', () => {
    const line = describeFreshness(state({ awaited_report: null }), MONDAY)

    expect(line.notes).toEqual([])
  })

  it('says a week the seller uploaded is in, and will be checked, instead of waiting for it', () => {
    const line = describeFreshness(
      state({ uploaded_report: { date_from: '2026-10-05', date_to: '2026-10-11' } }),
      MONDAY,
    )

    expect(line.notes).toEqual([
      {
        text: 'Report for 5–11 Oct uploaded from a file — checked against WB once the API serves it',
      },
    ])
  })

  it('points to "Upload report" in the ⓘ — the seller need not wait for the API', () => {
    expect(describeFreshness(state(), MONDAY).notes[0].hint).toContain('"Upload report"')
  })
})
