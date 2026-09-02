<script setup>
/**
 * The «Комментарий» row of the metrics table: one note per day.
 *
 * Collapsed to just its label until the chevron — or a click anywhere on the
 * row — opens it, so the table opens on numbers and the notes are there when
 * wanted.
 *
 * Every day is one card, open or collapsed — the same glass pane the
 * «Цены/Остатки» and «Действия» rows use, so the three bands below the grid
 * read as one thing.
 *
 * Each day has TWO independent fields: a one-line HEADER on top and the
 * free-text comment under it. Both are plain per-day values here — the header's
 * continuation onto a new day is done server-side at the day boundary and
 * arrives already stored, so nothing is inherited across columns on screen and
 * editing one day never touches another. Each input is a draft that commits on
 * blur — same as an inline cell edit, no per-day save button.
 *
 * Renders a `<tbody>`: it is a section of the parent's single `<table>`, which
 * is what lets each note sit in its own day column and scroll with it.
 */
import { ref, watch } from 'vue'

import { COLUMNS_PER_DAY } from '@/modules/labs/metricsMatrix'

const props = defineProps({
  /** @type {Array<{iso: string, label: string}>} oldest -> newest */
  days: { type: Array, required: true },
  /** Persisted day notes, keyed by ISO day: `{body, header}` per commented day. */
  comments: { type: Object, default: () => ({}) },
  /** ISO days whose note save is in flight (their input is disabled). */
  commentSavingDays: { type: Set, default: () => new Set() },
})

const emit = defineEmits(['comment'])

const commentsExpanded = ref(false)

/** The stored note of a day, or a blank one. */
function noteOf(iso) {
  return props.comments[iso] ?? { body: '', header: '' }
}

// Drafts by ISO day, one per field. Re-seeded from the persisted notes whenever
// they change (a SKU switch, a window change, a save) — except for the field
// being typed in, whose draft must survive a save landing elsewhere.
const commentDrafts = ref({})
const headerDrafts = ref({})
const focusedNote = ref(null) // `${iso}:body` | `${iso}:header` | null

watch(
  [() => props.comments, () => props.days],
  () => {
    const bodies = {}
    const headers = {}
    for (const day of props.days) {
      const note = noteOf(day.iso)
      bodies[day.iso] =
        focusedNote.value === `${day.iso}:body` ? (commentDrafts.value[day.iso] ?? '') : note.body
      headers[day.iso] =
        focusedNote.value === `${day.iso}:header`
          ? (headerDrafts.value[day.iso] ?? '')
          : note.header
    }
    commentDrafts.value = bodies
    headerDrafts.value = headers
  },
  { immediate: true, deep: true },
)

/** Commit one field on blur, but only when it differs from the stored value. */
function commitNote(iso, field) {
  if (focusedNote.value === `${iso}:${field}`) focusedNote.value = null
  const drafts = field === 'header' ? headerDrafts.value : commentDrafts.value
  const value = (drafts[iso] ?? '').trim()
  if (value === noteOf(iso)[field]) return
  // Only the edited field travels: the other keeps its stored value server-side.
  emit('comment', { day: iso, patch: { [field]: value } })
}
</script>

<template>
  <tbody class="matrix-comments">
    <tr class="matrix-gap" aria-hidden="true">
      <td :colspan="1 + days.length * COLUMNS_PER_DAY"></td>
    </tr>
    <tr>
      <td>
        <button
          type="button"
          class="comment-toggle"
          :aria-expanded="commentsExpanded"
          @click="commentsExpanded = !commentsExpanded"
        >
          <svg
            class="comment-chevron h-3 w-3 flex-none"
            :class="commentsExpanded && 'comment-chevron--open'"
            viewBox="0 0 24 24"
            fill="none"
            stroke="currentColor"
            stroke-width="2.4"
            stroke-linecap="round"
            stroke-linejoin="round"
          >
            <path d="m6 9 6 6 6-6" />
          </svg>
          <span class="text-micro font-semibold uppercase tracking-wide">Комментарии</span>
        </button>
      </td>
      <!-- Collapsed, ANY day cell (with or without a note) is a click
           target that opens the row — same as the chevron. -->
      <td
        v-for="day in days"
        :key="day.iso"
        :colspan="COLUMNS_PER_DAY"
        :class="!commentsExpanded && 'comment-cell--collapsed'"
        @click="commentsExpanded || (commentsExpanded = true)"
      >
        <!-- Collapsed or open, the day always gets its card: the band has to
             line up with the «Цены/Остатки» and «Действия» rows above and
             below it, and a strip of loose text between two rows of panes is
             what it looked like when it did not. -->
        <div class="day-comment-card" :class="!commentsExpanded && 'day-comment-card--collapsed'">
          <!-- Header on top, comment under it: the title is what carries
               onto the next day, the comment stays on its own. -->
          <template v-if="commentsExpanded">
            <input
              v-model="headerDrafts[day.iso]"
              type="text"
              maxlength="200"
              class="comment-header-input"
              :disabled="commentSavingDays.has(day.iso)"
              :placeholder="`Заголовок за ${day.label}`"
              :aria-label="`Заголовок за ${day.label}`"
              @focus="focusedNote = `${day.iso}:header`"
              @blur="commitNote(day.iso, 'header')"
              @keydown.enter.prevent="$event.target.blur()"
              @keydown.esc.prevent="$event.target.blur()"
            />
            <textarea
              v-model="commentDrafts[day.iso]"
              rows="2"
              maxlength="2000"
              class="comment-input"
              :disabled="commentSavingDays.has(day.iso)"
              :placeholder="`Заметка за ${day.label}`"
              :aria-label="`Комментарий за ${day.label}`"
              @focus="focusedNote = `${day.iso}:body`"
              @blur="commitNote(day.iso, 'body')"
              @keydown.esc.prevent="$event.target.blur()"
            ></textarea>
          </template>
          <!-- Collapsed: a dot marks the days that DO carry a note, so the
               row still says where to look before it is opened. The header
               leads, since it is the day's title. A day with no note keeps its
               card and leaves it empty — the band stays even. -->
          <span
            v-else-if="noteOf(day.iso).header || noteOf(day.iso).body"
            class="comment-dot"
            :title="[noteOf(day.iso).header, noteOf(day.iso).body].filter(Boolean).join(' — ')"
          >
            <span class="comment-dot-mark" aria-hidden="true"></span>
            <span v-if="noteOf(day.iso).header" class="comment-dot-header">
              {{ noteOf(day.iso).header }}
            </span>
            <span class="comment-dot-text">{{ noteOf(day.iso).body }}</span>
          </span>
        </div>
      </td>
    </tr>
  </tbody>
</template>

<style scoped src="./styles/MatrixCommentsRow.css"></style>
