/**
 * What moves a test's photo: the three modes, the body they send, the words.
 *
 * Three places ask the same question — the create form, the inline editor on a
 * running test, and the header that states the setting in words — and they
 * used to answer it three times. The answer is not obvious enough for that:
 * which fields may travel depends on the mode, and the API REFUSES a body
 * carrying a setting the chosen mode would not read rather than dropping it.
 *
 * The modes, and what each one bounds:
 *
 * * `impressions` — equal audience per photo. The sound default: every photo
 *   gets the same number of chances, so a CTR difference is a difference in
 *   the photo.
 * * `time` — equal wall clock per photo. Not a way round the advertising: with
 *   nothing serving the card there is nothing to measure, and the rotation
 *   pauses in this mode exactly as it does in the others.
 * * `either` — both bounds at once, and the turn ends at whichever is reached
 *   first. For a card whose advertising is uneven: the budget still gives a
 *   photo its audience while traffic is there, and the slot stops it standing
 *   on the card all day once traffic dries up.
 */

import { formatNumber } from '@/core/utils/format'

/** The modes as the picker offers them, in the order it lists them. */
export const TRIGGER_MODES = [
  { value: 'impressions', label: 'По показам' },
  { value: 'time', label: 'По времени' },
  { value: 'either', label: 'Показы и время' },
]

/** Does this mode read the impression budget? */
export function usesBudget(mode) {
  return mode === 'impressions' || mode === 'either'
}

/** Does this mode read the slot length? */
export function usesSlot(mode) {
  return mode === 'time' || mode === 'either'
}

/**
 * The trigger fields of a request body, for the mode in force.
 *
 * Only what the mode reads travels: sending the other one is a 422, not a
 * silently dropped field.
 *
 * @param {{trigger_mode: string, impression_budget: number|string,
 *   slot_minutes: number|string}} draft A form's own state.
 * @returns {object} `{trigger_mode, …}` ready to be merged into a body.
 */
export function triggerPayload(draft) {
  const mode = draft.trigger_mode
  return {
    trigger_mode: mode,
    ...(usesBudget(mode) ? { impression_budget: Number(draft.impression_budget) } : {}),
    ...(usesSlot(mode) ? { slot_minutes: Number(draft.slot_minutes) } : {}),
  }
}

/**
 * How a test rotates, in words — naming only the bounds its mode uses.
 *
 * @param {{trigger_mode: string, impression_budget: number, slot_minutes: number}|null} test
 * @returns {string} Empty while the test is still loading.
 */
export function triggerLabel(test) {
  if (!test) return ''
  const parts = []
  if (usesBudget(test.trigger_mode)) parts.push(`${formatNumber(test.impression_budget)} показов`)
  if (usesSlot(test.trigger_mode)) parts.push(`${formatNumber(test.slot_minutes)} мин`)
  // «или» ("or") rather than «и» ("and"): both are set, and the FIRST one
  // reached ends the turn. «каждые 1 000 показов и 20 минут» ("every 1,000
  // impressions and 20 minutes") would read as a test waiting for both,
  // which is the opposite of what the mode does.
  return `Смена фото каждые ${parts.join(' или ')}`
}
