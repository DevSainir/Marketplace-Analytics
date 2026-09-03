<script setup>
/**
 * A password input with a reveal toggle.
 *
 * Shared rather than repeated because the toggle has more moving parts than it
 * looks: the button must not submit the form it sits in, must not take the
 * field's place in the tab order for someone who never uses it, and must
 * announce its own state rather than relying on the icon.
 *
 * Revealing is a real affordance, not a nicety — this app asks for a password
 * that must contain both cases, and the commonest way to fail that on a phone
 * is to mistype it invisibly.
 */
import { ref } from 'vue'

defineProps({
  modelValue: { type: String, default: '' },
  autocomplete: { type: String, default: 'current-password' },
  placeholder: { type: String, default: '••••••••' },
  required: { type: Boolean, default: true },
  minlength: { type: [Number, String], default: 8 },
})

defineEmits(['update:modelValue'])

const revealed = ref(false)
</script>

<template>
  <div class="relative">
    <input
      :value="modelValue"
      :type="revealed ? 'text' : 'password'"
      :autocomplete="autocomplete"
      :placeholder="placeholder"
      :required="required"
      :minlength="minlength"
      class="password-input"
      @input="$emit('update:modelValue', $event.target.value)"
    />
    <button
      type="button"
      class="password-toggle"
      :aria-label="revealed ? 'Скрыть пароль' : 'Показать пароль'"
      :aria-pressed="revealed"
      :title="revealed ? 'Скрыть пароль' : 'Показать пароль'"
      @click="revealed = !revealed"
    >
      <!-- Drawn inline: two icons, no icon dependency, and `currentColor` keeps
           them on the same muted grey as the placeholder. -->
      <svg
        v-if="!revealed"
        viewBox="0 0 24 24"
        fill="none"
        stroke="currentColor"
        stroke-width="1.8"
        stroke-linecap="round"
        stroke-linejoin="round"
        aria-hidden="true"
      >
        <path d="M2 12s3.6-6.5 10-6.5S22 12 22 12s-3.6 6.5-10 6.5S2 12 2 12Z" />
        <circle cx="12" cy="12" r="2.75" />
      </svg>
      <svg
        v-else
        viewBox="0 0 24 24"
        fill="none"
        stroke="currentColor"
        stroke-width="1.8"
        stroke-linecap="round"
        stroke-linejoin="round"
        aria-hidden="true"
      >
        <path d="M10.6 6.2A9.9 9.9 0 0 1 12 5.5c6.4 0 10 6.5 10 6.5a18 18 0 0 1-3.3 4.05" />
        <path d="M6.4 7.9A17.7 17.7 0 0 0 2 12s3.6 6.5 10 6.5a10 10 0 0 0 3.9-.78" />
        <path d="M9.9 9.9a3 3 0 0 0 4.2 4.2" />
        <path d="m3 3 18 18" />
      </svg>
    </button>
  </div>
</template>

<style scoped>
/* `pr-11` reserves the toggle's column so a long password scrolls under the
   label rather than behind the icon. */
.password-input {
  @apply h-10 w-full rounded-input border border-border-subtle bg-canvas px-md pr-11 text-base text-primary placeholder:text-muted focus:outline-none focus:ring-2 phone:h-11;
}

.password-input:focus {
  border-color: var(--ui-action);
  --tw-ring-color: color-mix(in srgb, var(--ui-action) 20%, transparent);
}

.password-toggle {
  @apply absolute inset-y-0 right-0 flex w-11 items-center justify-center rounded-input transition;
  color: var(--ui-faint);
}

.password-toggle:hover {
  color: var(--ui-muted);
}

.password-toggle:focus-visible {
  outline: 2px solid var(--ui-action);
  outline-offset: -2px;
}

.password-toggle svg {
  width: 20px;
  height: 20px;
}
</style>
