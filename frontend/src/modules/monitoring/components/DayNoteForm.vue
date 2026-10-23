<script setup>
/**
 * The day's note on a phone — the `MatrixCommentsRow` of the day list.
 *
 * Two independent fields: a one-line HEADER on top and the free-text comment
 * under it. The header is the day's title and is the one that carries onto a
 * new day (server-side, at the day boundary); the comment stays on its own. Each
 * commits on blur, and only when it differs from what is stored — the same rule
 * the table row follows, because they write through the same endpoint.
 *
 * The draft of the field being typed in must survive the props changing under
 * it: a save landing on the OTHER field re-sends the whole note, and a naive
 * re-seed would wipe half-typed text. `focused` is what protects it.
 */
import { ref, watch } from 'vue'

const props = defineProps({
  /** @type {{iso: string, label: string}} The day on screen. */
  day: { type: Object, required: true },
  /** @type {{header: string, body: string}} The stored note, or blanks. */
  note: { type: Object, default: () => ({ header: '', body: '' }) },
  /** True while this day's note is being saved (its inputs are disabled). */
  saving: { type: Boolean, default: false },
})

const emit = defineEmits(['comment'])

const header = ref('')
const body = ref('')
const focused = ref(null) // 'header' | 'body' | null

watch(
  [() => props.note, () => props.day],
  () => {
    if (focused.value !== 'header') header.value = props.note.header ?? ''
    if (focused.value !== 'body') body.value = props.note.body ?? ''
  },
  { immediate: true, deep: true },
)

/** Commit one field on blur, but only when it differs from the stored value. */
function commit(field) {
  if (focused.value === field) focused.value = null
  const value = (field === 'header' ? header.value : body.value).trim()
  if (value === (props.note[field] ?? '')) return
  // Only the edited field travels: the other keeps its stored value server-side.
  emit('comment', { day: props.day.iso, patch: { [field]: value } })
}
</script>

<template>
  <section class="mt-md">
    <h3 class="mb-xs text-tiny font-medium uppercase text-muted">Comment</h3>

    <input
      v-model="header"
      type="text"
      maxlength="200"
      class="ui-input w-full font-medium"
      :disabled="saving"
      :placeholder="`Title for ${day.label}`"
      :aria-label="`Title for ${day.label}`"
      @focus="focused = 'header'"
      @blur="commit('header')"
      @keydown.enter.prevent="$event.target.blur()"
      @keydown.esc.prevent="$event.target.blur()"
    />

    <textarea
      v-model="body"
      rows="3"
      maxlength="2000"
      class="ui-input mt-xs w-full h-auto py-sm"
      :disabled="saving"
      :placeholder="`Note for ${day.label}`"
      :aria-label="`Comment for ${day.label}`"
      @focus="focused = 'body'"
      @blur="commit('body')"
      @keydown.esc.prevent="$event.target.blur()"
    ></textarea>
  </section>
</template>
