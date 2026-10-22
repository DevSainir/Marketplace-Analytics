/**
 * The app's one confirmation for an action that cannot be undone: the first
 * press asks "Really delete?", the second one does it, and a question left
 * unanswered withdraws itself after a few seconds.
 *
 * Pages used to do this four ways — three wordings ("Sure?", "Really
 * delete?", "Really delete the test?"), a reset after four seconds on one page
 * and never on the others, a red armed state on one and a neutral one on
 * another — and "Revoke", "Finish all" and "Clear" fired on the first
 * press. A browser `confirm()` was never the answer: it is off-brand, blocks
 * the page and reads the same for every action.
 *
 * One control is armed at a time: arming another withdraws the first, so a
 * stray second press elsewhere can never confirm something the reader is no
 * longer looking at.
 */
import { onBeforeUnmount, ref } from 'vue'

/** How long an unanswered "Really …?" stands before it withdraws itself. */
export const CONFIRM_RESET_MS = 4000

/**
 * The question a button asks once armed: "Delete test" → "Really delete test?".
 *
 * @param {string} label The button's own label.
 * @returns {string}
 */
export function confirmLabel(label) {
  return `Really ${label.charAt(0).toLowerCase()}${label.slice(1)}?`
}

/**
 * @returns {{
 *   isArmed: (key: unknown) => boolean,
 *   press: (key: unknown, action: () => void) => void,
 *   disarm: () => void,
 * }} `key` tells apart the controls of one list (a row id); a lone button
 * passes any constant.
 */
export function useConfirmClick() {
  const armed = ref(null)
  let timer = null

  function disarm() {
    clearTimeout(timer)
    timer = null
    armed.value = null
  }

  function press(key, action) {
    if (armed.value !== key) {
      disarm()
      armed.value = key
      timer = setTimeout(disarm, CONFIRM_RESET_MS)
      return
    }
    disarm()
    action()
  }

  onBeforeUnmount(disarm)

  return { isArmed: (key) => armed.value === key, press, disarm }
}
