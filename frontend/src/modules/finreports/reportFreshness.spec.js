/**
 * The freshness line's wording rules.
 *
 * This line exists because a P&L that stops nine days ago is usually a quiet
 * week and occasionally a dead harvester, and the page used to show the two
 * identically. So the assertions here are mostly about what it must NOT say: a
 * check that failed is never «нового ничего нет», and a stale check never reads
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
  it('keeps WB’s own day-month shape for a week inside one month', () => {
    expect(formatPeriod(report())).toBe('10–16 авг')
  })

  it('names both months when the week straddles two', () => {
    expect(formatPeriod(report({ date_from: '2026-07-28', date_to: '2026-08-03' }))).toBe(
      '28 июл – 3 авг',
    )
  })

  it('does not shift a calendar date into another day', () => {
    // A report's period is a calendar day, not an instant. Parsed through
    // `new Date('2026-08-16')` it is midnight UTC and prints as the 15th for
    // every reader west of Greenwich.
    expect(formatPeriod(report({ date_from: '2026-08-16', date_to: '2026-08-16' }))).toBe(
      '16–16 авг',
    )
  })

  it('says which endpoint it has when WB stated only one', () => {
    expect(formatPeriod(report({ date_from: null }))).toBe('по 16 авг')
  })

  it('is empty for a header WB stated no period for', () => {
    expect(formatPeriod(report({ date_from: null, date_to: null }))).toBe('')
  })
})

describe('formatCheckDay', () => {
  it('names the local day of the last check', () => {
    expect(formatCheckDay('2026-08-15T09:00:00Z')).toMatch(/^1[45] авг$/)
  })

  it('is empty for something that is not an instant', () => {
    expect(formatCheckDay('когда-то')).toBe('')
  })
})

describe('describeFreshness', () => {
  it('names the last weekly report and how far the daily ones reach', () => {
    // The statement runs past the weekly report on WB's per-day reports. The
    // weekly period alone over figures that run further reads as «а как?».
    const line = describeFreshness(
      {
        latest_report: report(),
        last_check: check({ outcome: 'up_to_date' }),
        provisional_through: '2026-08-17',
      },
      NOW,
    )

    expect(line.text).toBe('Последний еженедельный отчёт WB: 10–16 авг · ежедневные — по 17 авг')
    expect(line.tone).toBe('muted')
  })

  it('says nothing about daily reports that do not reach past the weekly one', () => {
    const line = describeFreshness(
      { latest_report: report(), last_check: check({ outcome: 'up_to_date' }) },
      NOW,
    )

    expect(line.text).toBe('Последний еженедельный отчёт WB: 10–16 авг')
  })

  it('does not say how long ago a fresh check ran', () => {
    // «проверено 12 мин назад» on every load was noise; only a stale check
    // earns its date (below).
    const line = describeFreshness({ latest_report: report(), last_check: check() }, NOW)

    expect(line.text).not.toMatch(/провер/)
    expect(line.text).not.toContain('загружен')
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

    expect(line.text).toContain('WB ещё не выложил ежедневный отчёт за 17 авг')
    expect(line.tone).toBe('muted')
  })

  it('does not call WB late for a day that is not over yet', () => {
    const line = describeFreshness(
      { latest_report: report(), last_check: check(), provisional_through: '2026-08-17' },
      new Date('2026-08-18T09:00:00'),
    )

    expect(line.text).toContain('WB ещё не выложил новых отчётов')
    expect(line.text).not.toContain('за 18 авг')
  })

  it('never phrases a failed check as «нового ничего нет»', () => {
    // The rule the whole feature turns on: WB not answering is an unanswered
    // question. Reporting silence as reassurance is the failure this line was
    // added to prevent, not one it may reintroduce.
    const line = describeFreshness(
      { latest_report: report(), last_check: check({ outcome: 'probe_failed' }) },
      NOW,
    )

    expect(line.text).not.toMatch(/не выложил/)
    expect(line.text).toContain('WB не ответил — возможно, есть отчёты новее')
    expect(line.tone).toBe('warning')
  })

  it('warns once nobody has asked in over a day, and says when it last did', () => {
    // A confident «нового ничего нет» from yesterday is what a dead harvester
    // looks like — the same words as a healthy quiet week, and only the age
    // separates them.
    const line = describeFreshness(
      {
        latest_report: report(),
        last_check: check({ outcome: 'up_to_date', checked_at: '2026-08-16T09:00:00Z' }),
      },
      NOW,
    )

    expect(line.text).toMatch(/последняя проверка WB — 1[56] авг$/)
    expect(line.tone).toBe('warning')
  })

  it('admits it does not know when no check is recorded', () => {
    // Redis did not answer, the record expired, or it came back in an unknown
    // shape: all three arrive as null, and none may read as «нового ничего нет».
    const line = describeFreshness({ latest_report: report(), last_check: null }, NOW)

    expect(line.text).toContain(
      'Не знаем, когда последний раз проверяли WB — данные могут быть неполными',
    )
    expect(line.tone).toBe('warning')
  })

  it('does not narrate an outcome this build does not know', () => {
    const line = describeFreshness(
      { latest_report: report(), last_check: check({ outcome: 'something_new' }) },
      NOW,
    )

    expect(line.text).toBe('Последний еженедельный отчёт WB: 10–16 авг')
  })

  it('says only that it is loading on a workspace with no reports yet', () => {
    const line = describeFreshness(
      { latest_report: null, last_check: check({ outcome: 'never_harvested' }) },
      NOW,
    )

    expect(line.text).toBe('Загружаем отчёты из WB…')
  })

  it('says the workspace has no reports rather than inventing a period', () => {
    const line = describeFreshness(
      { latest_report: null, last_check: check({ outcome: 'probe_failed' }) },
      NOW,
    )

    expect(line.text).toContain('Отчётов WB пока нет')
  })

  it('renders nothing when the state could not be fetched', () => {
    // The statement has its own error channel; a footnote must not shout over
    // what it annotates.
    expect(describeFreshness(null, NOW)).toBeNull()
    expect(describeFreshness({ latest_report: null, last_check: null }, NOW)).toBeNull()
  })
})

describe('a WB rate block', () => {
  it('is never worded as «нового ничего нет»', () => {
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

    expect(line.text).toContain('WB временно ограничил запросы — загрузим сами, когда откроет')
    expect(line.text).not.toContain('не выложил')
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
