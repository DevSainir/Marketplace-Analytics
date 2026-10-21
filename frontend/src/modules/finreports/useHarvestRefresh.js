/**
 * «Обновить» — ask WB now for a settlement report we do not already hold.
 *
 * The schedule asks WB hourly, which covers most of the gap between a report
 * being published and the P&L showing it — but not all of it. A report
 * published at 02:00 waits for the 08:00 tick, and an hour the worker was down
 * for is an hour nobody asked. In both cases the seller can already see the
 * report on WB's own site, and «подождите до утра» is not an answer.
 *
 * **The click answers in one round trip and then gets out of the way.** It used
 * to hold the button and a spinner for as long as the harvest ran, which on
 * 2026-09-09 meant seven minutes — of which six were the walk sitting still
 * waiting out WB's fifteen-minute settlement block, an outcome that was already
 * knowable before anything was enqueued. Three answers, all immediate:
 *
 * * WB will not take a settlement request yet → say when it will, enqueue
 *   nothing. There is no version of waiting that helps here.
 * * A harvest is already running → say so. The work is happening.
 * * Otherwise → enqueued, and it runs in the background.
 *
 * What the seller learns *afterwards* is the freshness line's job, not the
 * button's: a quiet watcher keeps polling, refreshes the line for free, and
 * reloads the statement if a week actually lands. It never disables anything,
 * so a slow harvest can no longer hold the page hostage.
 *
 * That watcher survives a reload, and it takes **two** sources, because neither
 * covers the whole run on its own:
 *
 * * The server's `running` flag — the harvest lock — which is the only thing
 *   that knows about a run somebody ELSE started. The lock is platform-wide, so
 *   a colleague's click, or the hourly schedule, is exactly as much "a harvest
 *   is running" as your own.
 * * A note this browser writes at the click (`pendingRefresh.js`), because the
 *   lock is held by the TASK and the task is not the click. Nothing holds it
 *   between the POST returning and the worker picking the job up, and nothing
 *   holds it after the task ends — yet in both windows the seller is still
 *   owed an answer, and a reload landing in either one saw `running: false` and
 *   dropped the state.
 *
 * `resumeWatch` reads both, which is also why a reload after the run finished
 * reports the OUTCOME rather than nothing: the note carries the settlement day
 * the click was measured against, so the answer is still computable.
 *
 * One thing this deliberately does NOT decide: what to do with new data. The
 * caller's `onNewReports` owns that, because what a new week means for the
 * visible period is a question about the period, not about harvesting.
 */
import { ref } from 'vue'

import { extractErrorMessage } from '@/core/api/axios'
import { fetchHarvestState, triggerHarvest } from '@/modules/finreports/api'
import {
  clearPendingRefresh,
  readPendingRefresh,
  writePendingRefresh,
} from '@/modules/finreports/pendingRefresh'

/** How often the background watcher asks whether the harvest has finished. */
const POLL_MS = 5000

/**
 * How many polls before the watcher gives up. The walk paces itself against
 * WB's ~1 req/min surfaces, so a run is minutes long; 20 minutes is past any we
 * have measured. Giving up stops only the *watching* — the harvest keeps going
 * on the worker, and nothing on screen was waiting on it anyway.
 */
const POLL_LIMIT = 240

/**
 * What the page says while a harvest is in flight.
 *
 * It names WHO, because «уже идёт» on its own reads as "you already clicked
 * this" and left a seller wondering how long ago that was. The harvest lock is
 * platform-wide and the schedule takes it hourly, so the run being reported is
 * very often not the reader's at all.
 */
const RUNNING_NOTICE =
  'Обновление уже идёт — его запустили вы или расписание. Отчёты появятся сами.'

/** Confirmation that a harvest was enqueued and is now somebody else's problem. */
const STARTED_NOTICE = 'Запустили обновление — оно идёт в фоне, отчёты появятся сами.'

/** Resolves after `ms`, so the poll below reads as a loop rather than a chain. */
function delay(ms) {
  return new Promise((resolve) => setTimeout(resolve, ms))
}

/**
 * WB's block, in the units a person waits in.
 *
 * Always rounded UP and never below one minute: telling somebody to come back
 * in «0 минут» invites the click that restarts WB's window, which is the exact
 * mistake this message exists to prevent.
 *
 * @param {number} seconds Seconds until WB accepts a settlement request.
 * @returns {string} A minutes phrase.
 */
export function formatRetryAfter(seconds) {
  const minutes = Math.max(1, Math.ceil((Number(seconds) || 0) / 60))
  return `${minutes} мин`
}

/**
 * @param {object} options
 * @param {() => string} options.currentSettled Last settlement day already on
 *   screen, read at click time. Compared against the day the harvest ends on:
 *   a run that pulled a week and a run that found nothing are both successes,
 *   and this is the only thing that tells them apart.
 * @param {() => Promise<void>} options.onNewReports Called once, after a run
 *   that moved the settlement day, to reload what it changed.
 * @param {(state: object) => void} [options.onState] Called with every state
 *   the watcher reads. The P&L's freshness line is built from exactly this
 *   answer, so reusing the poll is what keeps the line describing the run the
 *   seller just started rather than the situation before it.
 */
export function useHarvestRefresh({ currentSettled, onNewReports, onState }) {
  /**
   * Whether the button's own request is in flight.
   *
   * The ONLY thing that disables the button, and it lasts one round trip. It
   * used to stay true for the length of the harvest, which is what made a
   * fifteen-minute WB block look like a broken page.
   */
  const harvestBusy = ref(false)
  const harvestNotice = ref('')
  const harvestError = ref('')

  /**
   * Whether a watcher loop is already running.
   *
   * Not derivable from anything on screen, and that is the point: the watcher
   * is invisible now. Two loops over one harvest would fire `onNewReports`
   * twice for one arrival — two statement reloads, and the period jumping
   * forward twice.
   */
  let watching = false

  /**
   * Watch a harvest to its end, in the background. Never awaited by a click.
   *
   * `quiet` is a run this browser did not ask for: it still reloads the
   * statement if a week lands, but «новых отчётов нет» would answer a question
   * nobody asked.
   */
  async function watchHarvest(settledBefore, { quiet = false } = {}) {
    if (watching) return
    watching = true
    try {
      await pollUntilIdle(settledBefore, quiet)
    } finally {
      watching = false
    }
  }

  /** The loop itself. See `watchHarvest`, which owns the `watching` flag. */
  async function pollUntilIdle(settledBefore, quiet) {
    for (let attempt = 0; attempt < POLL_LIMIT; attempt += 1) {
      await delay(POLL_MS)
      let state
      try {
        state = await fetchHarvestState()
      } catch {
        // A dropped poll says nothing about the harvest — keep watching.
        continue
      }
      onState?.(state)
      if (state.running) continue
      await concludeHarvest(state, settledBefore, quiet)
      return
    }
    // The note goes too: nothing is watching this run any more, so the next
    // reload must not resume a wait nobody is reporting on.
    clearPendingRefresh()
  }

  /**
   * Say how a finished harvest ended, and stop calling it pending.
   *
   * Both endings are successes and only the settlement day tells them apart,
   * which is why the baseline is threaded this far rather than read off the
   * store: by the time this runs, the store may already hold the new week.
   *
   * @param {{latest_settled: string|null}|null} state The state that showed it idle.
   * @param {string} settledBefore Settlement day when the refresh was asked for.
   * @param {boolean} [quiet] Nobody here asked: announce a new report, not its absence.
   */
  async function concludeHarvest(state, settledBefore, quiet = false) {
    clearPendingRefresh()
    // An EMPTY baseline is "we did not know", not "we knew it was nothing" —
    // a click that beat the weeks onto the page has no day to compare against,
    // and every real day differs from an empty string, so announcing on that
    // comparison would report an ordinary quiet run as a new report.
    if (settledBefore && state?.latest_settled && state.latest_settled !== settledBefore) {
      await onNewReports()
      harvestNotice.value = `Загружен отчёт по ${state.latest_settled}.`
    } else if (!quiet) {
      harvestNotice.value = 'Новых отчётов у Wildberries пока нет.'
    }
  }

  /**
   * Pick a refresh back up after a page load.
   *
   * Three endings, decided by the server's `running` flag together with this
   * browser's note (see the module docstring on why neither is enough alone):
   *
   * * A harvest is running — watch it in the background. Say so only if this
   *   browser asked for it: the lock is platform-wide and the schedule takes it
   *   many times a day, so on an ordinary page load «Обновление уже идёт» was
   *   usually about somebody else's workspace and read as noise. A run that
   *   actually found a report for THIS workspace is the freshness line's to
   *   announce («WB выложил новый отчёт — загружаем»).
   * * Nothing is running but this browser asked for one — it finished while the
   *   tab was away, so report how it ended rather than silently dropping it.
   * * Neither — an ordinary page load, and nothing to say.
   *
   * The baseline is never `currentSettled()`: this runs before the weeks are
   * loaded, so the store's span is still empty, and every real day differs from
   * an empty string — a run that brought nothing would be announced as
   * «Загружен отчёт по …».
   *
   * @param {{running: boolean, latest_settled: string|null}|null} state
   */
  async function resumeWatch(state) {
    if (watching) return
    const pending = readPendingRefresh()
    if (!state?.running && !pending) return
    // The click's own baseline wins over the state we just read: by the time a
    // reload happens the history may already have moved, and comparing the new
    // day against itself would report a week that DID arrive as «новых отчётов
    // нет». Falling back to the state's day covers a run this browser never
    // asked for, where there is no click to have a baseline.
    const settledBefore = pending?.settled_before ?? state?.latest_settled ?? ''
    if (!state?.running) {
      // Asked for, and already over — the tab was closed for it. Awaited,
      // unlike the branch below: this one resolves in a round trip.
      await concludeHarvest(state, settledBefore)
      return
    }
    if (pending) {
      harvestNotice.value = RUNNING_NOTICE
      void watchHarvest(settledBefore)
      return
    }
    void watchHarvest(settledBefore, { quiet: true })
  }

  /**
   * Ask for a harvest and report, immediately, what came of asking.
   *
   * Returns as soon as the trigger answers. Whatever happens next happens in
   * `watchHarvest`, which nothing on screen is waiting on.
   */
  async function refreshFromWb() {
    if (harvestBusy.value) return
    // Claimed before the first await, not after the trigger returns: two clicks
    // in the same tick would otherwise both get past the check and POST twice.
    harvestBusy.value = true
    harvestError.value = ''
    harvestNotice.value = ''
    const settledBefore = currentSettled()
    let status
    let taskId
    let retryAfter
    try {
      ;({ status, task_id: taskId, retry_after_seconds: retryAfter } = await triggerHarvest())
    } catch (error) {
      harvestError.value = extractErrorMessage(error)
      return
    } finally {
      harvestBusy.value = false
    }
    if (status === 'rate_limited') {
      // Nothing was enqueued and nothing is coming, so there is nothing to
      // watch and no note to leave. WB will not take a settlement request until
      // its window rolls over, and a click inside that window restarts it.
      harvestNotice.value = `Ограничение по запросам от Wildberries — попробуйте через ${formatRetryAfter(retryAfter)}.`
      return
    }
    // Written before the watching starts, so a reload during the run — or after
    // it — still knows this browser asked and what day it was measured against.
    writePendingRefresh(taskId, settledBefore)
    harvestNotice.value = status === 'already_running' ? RUNNING_NOTICE : STARTED_NOTICE
    void watchHarvest(settledBefore)
  }

  return {
    harvestBusy,
    harvestNotice,
    harvestError,
    refreshFromWb,
    resumeWatch,
  }
}
