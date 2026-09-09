/**
 * «Обновить» — ask WB now for a settlement report we do not already hold, then
 * wait for the harvest to finish.
 *
 * The schedule asks WB hourly, which covers most of the gap between a report
 * being published and the P&L showing it — but not all of it. A report
 * published at 02:00 waits for the 08:00 tick, and an hour the worker was down
 * for is an hour nobody asked. In both cases the seller can already see the
 * report on WB's own site, and «подождите до утра» is not an answer.
 *
 * Two things this deliberately does NOT do. It does not decide whether a
 * harvest may run — the backend refuses to start a second one on top of a
 * running one, and this only reflects that back. And it does not decide what to
 * do with new data: the caller's `onNewReports` owns that, because what a new
 * week means for the visible period is a question about the period, not about
 * harvesting.
 *
 * A refresh in progress survives a reload, and that takes **two** sources,
 * because neither covers the whole wait on its own:
 *
 * * The server's `running` flag — the harvest lock — which is the only thing
 *   that knows about a run somebody ELSE started. The lock is platform-wide, so
 *   a colleague's click, or the hourly schedule, is exactly as much "a harvest
 *   is running" as your own.
 * * A note this browser writes at the click (`pendingRefresh.js`), because the
 *   lock is held by the TASK and the task is not the click. Nothing holds it
 *   between the POST returning and the worker picking the job up, and nothing
 *   holds it after the task ends — yet in both windows the seller is still
 *   waiting for what they asked for, and a reload landing in either one saw
 *   `running: false` and dropped the state.
 *
 * `resumeWatch` reads both, which is also why a reload after the run finished
 * shows the OUTCOME rather than a blank header: the note carries the settlement
 * day the click was measured against, so the answer is still computable.
 */
import { ref } from 'vue'

import { extractErrorMessage } from '@/core/api/axios'
import { fetchHarvestState, triggerHarvest } from '@/modules/finreports/api'
import {
  clearPendingRefresh,
  readPendingRefresh,
  writePendingRefresh,
} from '@/modules/finreports/pendingRefresh'

/** How often to ask whether the harvest has finished. */
const POLL_MS = 5000

/**
 * How many polls before we stop watching. The walk paces itself against WB's
 * ~1 req/min surfaces, so a fleet-wide run is minutes long; 20 minutes is past
 * any run we have measured. Giving up stops only the *watching* — the harvest
 * keeps going on the worker, which is what the closing message says.
 */
const POLL_LIMIT = 240

/**
 * What the page says while somebody else's harvest — or your own, from before
 * a reload — is in flight.
 *
 * It says WHO, because «уже идёт» on its own reads as "you already clicked
 * this" and left a seller wondering how long ago that was. The harvest lock is
 * platform-wide and the schedule takes it hourly, so the run being waited on is
 * very often not the reader's at all.
 */
const RUNNING_NOTICE =
  'Обновление уже идёт — его запустили вы или расписание. Ждём окончания, это несколько минут.'

/** Resolves after `ms`, so the poll below reads as a loop rather than a chain. */
function delay(ms) {
  return new Promise((resolve) => setTimeout(resolve, ms))
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
 *   the poll reads. The P&L's freshness line is built from exactly this answer,
 *   so reusing the poll is what keeps the line describing the run the seller
 *   just watched finish rather than the situation before it.
 */
export function useHarvestRefresh({ currentSettled, onNewReports, onState }) {
  const harvestRunning = ref(false)
  const harvestNotice = ref('')
  const harvestError = ref('')

  /**
   * Whether a poll loop is already in flight.
   *
   * Not the same question as `harvestRunning`, and not derivable from it: a
   * click sets `harvestRunning` before the POST resolves, and the mounted view
   * may adopt a running harvest in the same tick. Two loops polling the same
   * harvest would fire `onNewReports` twice over one arrival.
   */
  let watching = false

  /** Poll until the harvest stops, then report which ending it was. */
  async function watchHarvest(settledBefore) {
    watching = true
    try {
      return await pollUntilIdle(settledBefore)
    } finally {
      watching = false
    }
  }

  /** The loop itself. See `watchHarvest`, which owns the `watching` flag. */
  async function pollUntilIdle(settledBefore) {
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
      await concludeHarvest(state, settledBefore)
      return
    }
    harvestRunning.value = false
    // The note goes too: the page has stopped claiming to watch this run, so
    // the next reload must not resume a wait nothing is reporting on.
    clearPendingRefresh()
    harvestNotice.value = 'Обновление идёт дольше обычного — оно продолжится в фоне.'
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
   */
  async function concludeHarvest(state, settledBefore) {
    harvestRunning.value = false
    clearPendingRefresh()
    if (state?.latest_settled && state.latest_settled !== settledBefore) {
      await onNewReports()
      harvestNotice.value = `Загружен отчёт по ${state.latest_settled}.`
    } else {
      harvestNotice.value = 'Новых отчётов у Wildberries пока нет.'
    }
  }

  /**
   * Pick a refresh back up after a page load.
   *
   * Three endings, and which one applies is decided by the server's `running`
   * flag together with this browser's note (see the module docstring on why
   * neither is enough alone):
   *
   * * A harvest is running — adopt it, so the reload comes back to the same
   *   disabled button and notice instead of pretending nothing is happening.
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
    if (harvestRunning.value || watching) return
    const pending = readPendingRefresh()
    if (!state?.running && !pending) return
    // The click's own baseline wins over the state we just read: by the time a
    // reload happens the history may already have moved, and comparing the new
    // day against itself would report a week that DID arrive as «новых отчётов
    // нет». Falling back to the state's day covers a run this browser never
    // asked for, where there is no click to have a baseline.
    const settledBefore = pending?.settled_before ?? state?.latest_settled ?? ''
    if (!state?.running) {
      // Asked for, and already over — the tab was closed for it. Nothing to
      // wait on, so report how it ended instead of spinning for five seconds
      // to rediscover that it is finished. Awaited, unlike the branch below:
      // this one resolves in a round trip, not in minutes.
      await concludeHarvest(state, settledBefore)
      return
    }
    harvestRunning.value = true
    harvestError.value = ''
    harvestNotice.value = RUNNING_NOTICE
    // Not awaited: the caller is a page load, and the wait is minutes long.
    void watchHarvest(settledBefore)
  }

  /** Trigger a harvest (unless one is running) and wait it out. */
  async function refreshFromWb() {
    if (harvestRunning.value) return
    // Claimed before the first await, not after the trigger returns: two clicks
    // in the same tick would otherwise both get past the check and POST twice.
    // The second harvest would find the lock held and do nothing, but a button
    // that queues work it knows is redundant is a bug on this side of the wire.
    harvestRunning.value = true
    harvestError.value = ''
    harvestNotice.value = ''
    const settledBefore = currentSettled()
    try {
      const { status, task_id: taskId } = await triggerHarvest()
      // Written before the wait, not after it: the whole point is to survive a
      // reload, and a reload during the wait is the case this covers.
      writePendingRefresh(taskId, settledBefore)
      harvestNotice.value =
        status === 'already_running' ? RUNNING_NOTICE : 'Спрашиваем Wildberries о новых отчётах…'
    } catch (error) {
      harvestRunning.value = false
      harvestError.value = extractErrorMessage(error)
      return
    }
    await watchHarvest(settledBefore)
  }

  return { harvestRunning, harvestNotice, harvestError, refreshFromWb, resumeWatch }
}
