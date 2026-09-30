<script setup>
/**
 * One article's hand-set norm, typed straight into the grid.
 *
 * Saved when the field is left (or on Enter), not per keystroke: a norm of 150
 * typed out must not be stored as 1, then 15. An empty field clears the norm
 * and the row goes back to the default one; anything that is not a number puts
 * the field back as it was. A comma is a decimal point, as a Russian keyboard
 * types it.
 */
import { ref, watch } from 'vue'

const props = defineProps({
  value: { type: Number, default: null },
  /** What the field is for, read out by a screen reader. */
  label: { type: String, required: true },
})
const emit = defineEmits(['commit'])

const shown = (value) => (value === null ? '' : String(value).replace('.', ','))
const draft = ref(shown(props.value))
watch(
  () => props.value,
  (value) => (draft.value = shown(value)),
)

function commit() {
  const text = draft.value.replace(/\s/g, '').replace(',', '.')
  if (text === '') return emit('commit', null)
  const value = Number(text)
  if (Number.isFinite(value)) emit('commit', value)
  else draft.value = shown(props.value)
}
</script>

<template>
  <input
    v-model="draft"
    class="hm-norm"
    type="text"
    inputmode="decimal"
    placeholder="—"
    :aria-label="label"
    @change="commit"
    @keydown.enter="$event.target.blur()"
  />
</template>
