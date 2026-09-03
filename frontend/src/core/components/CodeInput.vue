<script setup>
/**
 * One cell per digit, for the six-digit codes the recovery mails carry.
 *
 * The reason this is a component and not six inputs in a view: almost
 * everything about the pattern is a trap, and each trap has to be closed once
 * rather than per screen.
 *
 * - `maxlength="1"` SILENTLY TRUNCATES A PASTE to its first character, so
 *   Ctrl+V of `864346` fills one cell and drops five digits. The paste event
 *   is intercepted and spread across the cells instead.
 * - Browser and iOS autofill deliver the whole code into ONE field. That
 *   arrives as an ordinary `input` with a multi-character value, so the same
 *   spreading path handles it — `autocomplete="one-time-code"` is on the first
 *   cell, which is where every client puts it.
 * - Backspace in an empty cell has to reach BACKWARDS, or the code cannot be
 *   corrected without the mouse.
 * - A focused cell selects its content, so typing over a filled cell replaces
 *   rather than being rejected by the length cap.
 *
 * The model is the digits as one string (`'864346'`), which is what the API
 * takes; the cells are a rendering of it.
 */
import { computed, nextTick, ref, watch } from 'vue'

const props = defineProps({
  modelValue: { type: String, default: '' },
  length: { type: Number, default: 6 },
  // Paints the cells with the negative border. The message itself belongs to
  // the form, not here — this component never invents copy.
  invalid: { type: Boolean, default: false },
  disabled: { type: Boolean, default: false },
  autofocus: { type: Boolean, default: false },
  // Labelled by the form's own <span>, so screen readers announce the group
  // rather than six anonymous boxes.
  ariaLabel: { type: String, default: 'Код из письма' },
})

const emit = defineEmits(['update:modelValue', 'complete'])

const cells = ref([])

/** The model split into exactly `length` slots, padded with ''. */
const digits = computed(() => {
  const out = new Array(props.length).fill('')
  for (let i = 0; i < Math.min(props.modelValue.length, props.length); i += 1) {
    out[i] = props.modelValue[i]
  }
  return out
})

function focusCell(index) {
  const clamped = Math.max(0, Math.min(index, props.length - 1))
  const el = cells.value[clamped]
  if (el) {
    el.focus()
    el.select()
  }
}

/** Write `next` back to the model, and announce a full code once. */
function commit(next) {
  const value = next.join('').slice(0, props.length)
  emit('update:modelValue', value)
  if (value.length === props.length) emit('complete', value)
}

/**
 * Put `raw` into the cells starting at `from`, ignoring anything but digits.
 * This is the single path for typing, pasting and autofill.
 */
function spread(raw, from) {
  // Sanitised here too: `onPaste` hands over raw clipboard text.
  const incoming = String(raw).replace(/\D/g, '')
  const next = [...digits.value]
  let cursor = from
  for (const char of incoming) {
    if (cursor >= props.length) break
    next[cursor] = char
    cursor += 1
  }
  commit(next)
  nextTick(() => focusCell(cursor))
}

/**
 * Force every cell back to what the model says.
 *
 * Vue only patches the DOM when the bound value CHANGES, and two ordinary
 * keystrokes leave it unchanged: a rejected character (a letter, an emoji) and
 * a retyped identical digit. `onInput` blanks the cell before either is
 * evaluated, so without this the digit vanishes from the screen while staying
 * in the code — the person then fixes a cell that was never wrong.
 */
function syncCells() {
  digits.value.forEach((digit, index) => {
    const el = cells.value[index]
    if (el && el.value !== digit) el.value = digit
  })
}

function onInput(event, index) {
  const raw = event.target.value
  // The DOM is a scratchpad; the model is the truth. Blanking here is what lets
  // a `maxlength="1"` cell accept a replacement keystroke at all.
  event.target.value = ''
  const incoming = String(raw).replace(/\D/g, '')
  if (incoming) spread(incoming, index)
  nextTick(syncCells)
}

function onPaste(event) {
  event.preventDefault()
  const text = event.clipboardData?.getData('text') ?? ''
  // Always from the first cell: someone pasting a code means the whole code,
  // whichever box happened to hold focus.
  spread(text, 0)
}

function onKeydown(event, index) {
  const key = event.key
  if (key === 'Backspace') {
    event.preventDefault()
    const next = [...digits.value]
    if (next[index]) {
      next[index] = ''
      commit(next)
      return
    }
    // Empty cell: clear the one before it and go there.
    if (index > 0) {
      next[index - 1] = ''
      commit(next)
      focusCell(index - 1)
    }
    return
  }
  if (key === 'Delete') {
    event.preventDefault()
    const next = [...digits.value]
    next[index] = ''
    commit(next)
    return
  }
  if (key === 'ArrowLeft') {
    event.preventDefault()
    focusCell(index - 1)
    return
  }
  if (key === 'ArrowRight') {
    event.preventDefault()
    focusCell(index + 1)
    return
  }
  if (key === 'Home') {
    event.preventDefault()
    focusCell(0)
    return
  }
  if (key === 'End') {
    event.preventDefault()
    focusCell(props.length - 1)
  }
}

// Focus the first empty cell when the form clears the code (a refused attempt),
// so the next try starts where the person has to type.
watch(
  () => props.modelValue,
  (value) => {
    if (value === '') nextTick(() => focusCell(0))
  },
)

defineExpose({ focus: () => focusCell(0) })
</script>

<template>
  <div
    class="flex items-center justify-center gap-sm phone:gap-xs"
    role="group"
    :aria-label="ariaLabel"
  >
    <input
      v-for="(digit, index) in digits"
      :key="index"
      :ref="(el) => (cells[index] = el)"
      :value="digit"
      :disabled="disabled"
      :autofocus="autofocus && index === 0"
      :autocomplete="index === 0 ? 'one-time-code' : 'off'"
      :aria-label="`${ariaLabel}, ${index + 1}`"
      type="text"
      inputmode="numeric"
      pattern="[0-9]*"
      maxlength="1"
      class="code-cell"
      :class="invalid ? 'code-cell-invalid' : 'code-cell-idle'"
      @input="onInput($event, index)"
      @keydown="onKeydown($event, index)"
      @paste="onPaste"
      @focus="$event.target.select()"
    />
  </div>
</template>

<style scoped>
/* Inline utilities would repeat this eleven times across two forms. The
   `tabular-nums` matters: proportional digits make a `1` sit narrower than a
   `8` and the row stops looking like a row. */
.code-cell {
  @apply h-14 w-12 rounded-input border bg-canvas text-center text-h2 font-semibold tabular-nums text-primary transition focus:outline-none focus:ring-2 disabled:cursor-not-allowed disabled:opacity-60 phone:h-12 phone:w-10;
}

.code-cell-idle {
  @apply border-border-subtle focus:border-action focus:ring-action/20;
}

.code-cell-invalid {
  @apply border-status-negative/50 focus:border-status-negative focus:ring-status-negative/20;
}
</style>
