/**
 * How a page's period is remembered between visits — one rule for every page.
 *
 * Kept for an hour, per page and per кабинет; a window that meant «the latest
 * N days» comes back on the newest day there is now. The owner's rule that
 * started this: a period picked on the monitoring page and another on the P&L
 * must each come back as it was, not overwrite one another.
 */
import { setWorkspaceId } from '@/core/api/axios'
import { recallPeriod, rememberPeriod } from '@/core/utils/periodMemory'

/** The page's data as it stood at the choice, and after a new week arrived. */
const EDGE = { from: '2024-01-29', to: '2026-07-19' }
const EDGE_PLUS_A_WEEK = { from: '2024-01-29', to: '2026-07-26' }

beforeEach(() => {
  localStorage.clear()
  setWorkspaceId('ws-1')
  vi.useFakeTimers()
  vi.setSystemTime(new Date('2026-07-19T08:00:00Z'))
})

afterEach(() => {
  vi.useRealTimers()
})

describe('how long a chosen period lasts', () => {
  it('gives back a period chosen within the hour', () => {
    rememberPeriod('finreports', '2024-02-01', '2024-02-04', EDGE)

    vi.advanceTimersByTime(59 * 60 * 1000)

    expect(recallPeriod('finreports', EDGE)).toEqual({ from: '2024-02-01', to: '2024-02-04' })
  })

  it('forgets a period chosen more than an hour ago', () => {
    rememberPeriod('finreports', '2024-02-01', '2024-02-04', EDGE)

    vi.advanceTimersByTime(61 * 60 * 1000)

    expect(recallPeriod('finreports', EDGE)).toBeNull()
  })

  it('ignores a half-written or unreadable entry instead of throwing', () => {
    localStorage.setItem('period:finreports:ws-1', '{"from":"2024-02-01"}')
    expect(recallPeriod('finreports', EDGE)).toBeNull()

    localStorage.setItem('period:finreports:ws-1', 'not json')
    expect(recallPeriod('finreports', EDGE)).toBeNull()
  })
})

describe('whose period it is', () => {
  it('keeps each page apart', () => {
    rememberPeriod('monitoring', '2026-06-01', '2026-06-30')
    rememberPeriod('finreports', '2026-07-13', '2026-07-19', EDGE)

    expect(recallPeriod('monitoring')).toEqual({ from: '2026-06-01', to: '2026-06-30' })
    expect(recallPeriod('finreports', EDGE)).toEqual({ from: '2026-07-13', to: '2026-07-19' })
  })

  it('keeps each кабинет apart', () => {
    rememberPeriod('summary', '2026-06-01', '2026-06-30')

    setWorkspaceId('ws-2')

    expect(recallPeriod('summary')).toBeNull()
  })
})

describe('where a remembered period lands', () => {
  it('slides a window that ended on the then-newest day, keeping its length', () => {
    rememberPeriod('finreports', '2026-07-13', '2026-07-19', EDGE)

    expect(recallPeriod('finreports', EDGE_PLUS_A_WEEK)).toEqual({
      from: '2026-07-20',
      to: '2026-07-26',
    })
  })

  it('extends «Вся история» instead of sliding it', () => {
    // Anchored at both ends: preserving its LENGTH would walk the start forward
    // and quietly drop the oldest days out of the total.
    rememberPeriod('finreports', '2024-01-29', '2026-07-19', EDGE)

    expect(recallPeriod('finreports', EDGE_PLUS_A_WEEK)).toEqual({
      from: '2024-01-29',
      to: '2026-07-26',
    })
  })

  it('leaves a window that stopped short of the newest day where it was', () => {
    rememberPeriod('finreports', '2024-01-29', '2024-02-04', EDGE)

    expect(recallPeriod('finreports', EDGE_PLUS_A_WEEK)).toEqual({
      from: '2024-01-29',
      to: '2024-02-04',
    })
  })

  it('writes down where a followed window landed, without renewing its hour', () => {
    rememberPeriod('finreports', '2026-07-13', '2026-07-19', EDGE)
    vi.advanceTimersByTime(30 * 60 * 1000)
    recallPeriod('finreports', EDGE_PLUS_A_WEEK)

    vi.advanceTimersByTime(31 * 60 * 1000)

    // Following the data is not a fresh choice: the hour still runs from the click.
    expect(recallPeriod('finreports', EDGE_PLUS_A_WEEK)).toBeNull()
  })
})
