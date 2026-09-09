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
  formatElapsed,
  formatInstant,
  formatPeriod,
} from '@/modules/finreports/reportFreshness'

const NOW = new Date('2026-08-18T09:00:00Z')

/** The newest report on file: one WB week, pulled two days after it closed. */
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

describe('formatInstant', () => {
  it('reads the day and the time off the same local clock', () => {
    // The bug this guards: a 23:14Z harvest whose day comes from one source and
    // whose time comes from another prints them a day apart in Moscow. Whatever
    // timezone the test runs in, the two halves must agree with each other.
    const at = new Date('2026-08-17T23:14:00Z')
    const expectedTime = `${String(at.getHours()).padStart(2, '0')}:14`

    expect(formatInstant('2026-08-17T23:14:00Z')).toContain(String(at.getDate()))
    expect(formatInstant('2026-08-17T23:14:00Z')).toContain(expectedTime)
  })

  it('is empty for something that is not an instant', () => {
    expect(formatInstant('когда-то')).toBe('')
  })
})

describe('formatElapsed', () => {
  it('counts minutes inside the hour', () => {
    expect(formatElapsed('2026-08-18T08:48:00Z', NOW)).toBe('12 мин назад')
  })

  it('counts hours inside the day', () => {
    expect(formatElapsed('2026-08-18T04:00:00Z', NOW)).toBe('5 ч назад')
  })

  it('switches to an absolute date past a day', () => {
    // «2 дня назад» and «15 авг» say the same thing, and only the second can be
    // checked against anything — which is the point of the whole line.
    expect(formatElapsed('2026-08-15T09:00:00Z', NOW)).toMatch(/^1[45] авг$/)
  })

  it('reads a future instant as clock skew rather than as a countdown', () => {
    expect(formatElapsed('2026-08-18T09:00:30Z', NOW)).toBe('только что')
  })
})

describe('describeFreshness', () => {
  it('says what we hold, when we pulled it, and when we last asked', () => {
    const line = describeFreshness({ latest_report: report(), last_check: check() }, NOW)

    expect(line.text).toContain('Последний отчёт WB: 10–16 авг')
    expect(line.text).toContain('загружен')
    expect(line.text).toContain('Wildberries пока не опубликовал отчёт новее 10–16 авг')
    expect(line.text).toContain('проверено 12 мин назад')
  })

  it('reads a quiet week as normal, not as a problem', () => {
    // WB publishing nothing for days is the ordinary case. If it were rendered
    // as a warning the warning would be permanent, and permanent warnings are
    // read as decoration by the second week.
    const line = describeFreshness({ latest_report: report(), last_check: check() }, NOW)

    expect(line.tone).toBe('muted')
  })

  it('names the period we hold, not the days that were probed', () => {
    // The seller matches this string against WB's own отчёты page, which lists
    // report periods. The probe window («17 авг») appears nowhere there.
    const line = describeFreshness({ latest_report: report(), last_check: check() }, NOW)

    expect(line.text).not.toContain('17 авг')
  })

  it('never phrases a failed check as «нового ничего нет»', () => {
    // The rule the whole feature turns on: WB not answering is an unanswered
    // question. Reporting silence as reassurance is the failure this line was
    // added to prevent, not one it may reintroduce.
    const line = describeFreshness(
      { latest_report: report(), last_check: check({ outcome: 'probe_failed' }) },
      NOW,
    )

    expect(line.text).not.toMatch(/не опубликовал/)
    expect(line.text).toContain('Не удалось спросить Wildberries')
    expect(line.text).toContain('данные могут быть неполными')
    expect(line.tone).toBe('warning')
  })

  it('warns once nobody has asked in over a day', () => {
    // A confident «нового ничего нет» from yesterday is what a dead harvester
    // looks like — the same words as a healthy quiet week, and only the age
    // separates them.
    const line = describeFreshness(
      { latest_report: report(), last_check: check({ checked_at: '2026-08-16T09:00:00Z' }) },
      NOW,
    )

    expect(line.tone).toBe('warning')
  })

  it('admits it does not know when no check is recorded', () => {
    // Never checked, the record expired, or it came back corrupt: all three
    // arrive as null, and none of them may be rendered as «нового ничего нет».
    const line = describeFreshness({ latest_report: report(), last_check: null }, NOW)

    expect(line.text).toContain('неизвестно, когда мы в последний раз спрашивали')
    expect(line.tone).toBe('warning')
  })

  it('does not narrate an outcome this build does not know', () => {
    const line = describeFreshness(
      { latest_report: report(), last_check: check({ outcome: 'something_new' }) },
      NOW,
    )

    expect(line.text).toContain('Последний отчёт WB: 10–16 авг')
    expect(line.text).toContain('проверено 12 мин назад')
    expect(line.text).not.toContain('Wildberries пока не опубликовал')
  })

  it('says the workspace has no reports rather than inventing a period', () => {
    const line = describeFreshness(
      { latest_report: null, last_check: check({ outcome: 'never_harvested' }) },
      NOW,
    )

    expect(line.text).toContain('Отчётов WB пока нет')
    expect(line.text).toContain('Загружаем всё, что есть у Wildberries')
  })

  it('renders nothing when the state could not be fetched', () => {
    // The statement has its own error channel; a footnote must not shout over
    // what it annotates.
    expect(describeFreshness(null, NOW)).toBeNull()
    expect(describeFreshness({ latest_report: null, last_check: null }, NOW)).toBeNull()
  })
})
