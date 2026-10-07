<script setup>
/**
 * Redeeming an activation key.
 *
 * Shared by the blocked-page overlay (`ActivationGate`) and the profile page,
 * which are the two places somebody can be when they need it: stopped in front
 * of a section they cannot reach, or looking for where to type the key they
 * were just handed. One implementation, so the second place cannot drift into
 * a slightly different form with a slightly different error.
 */
import { ref } from 'vue'

import { useMembersStore } from '@/modules/profile/membersStore'

defineProps({
  // The overlay centres its copy; the profile card reads left-aligned like the
  // rows above it.
  align: { type: String, default: 'center' },
})

const members = useMembersStore()
const code = ref('')

async function submit() {
  if (!code.value.trim() || members.saving === 'activation') return
  await members.activate(code.value.trim())
}
</script>

<template>
  <form class="flex flex-col gap-sm" @submit.prevent="submit">
    <label class="block">
      <span class="mb-xs block text-tiny font-medium text-muted" :class="`text-${align}`">
        Ключ активации
      </span>
      <input
        v-model="code"
        type="text"
        required
        autocomplete="off"
        spellcheck="false"
        placeholder="XXXX-XXXX-XXXX"
        class="key-input"
        :class="align === 'center' ? 'text-center' : ''"
      />
    </label>

    <p v-if="members.error" class="key-error">{{ members.error }}</p>

    <button
      type="submit"
      :disabled="members.saving === 'activation' || !code.trim()"
      class="key-button"
    >
      {{ members.saving === 'activation' ? 'Проверяем…' : 'Активировать' }}
    </button>
  </form>
</template>

<style scoped>
.key-input {
  @apply h-10 w-full rounded-input border border-border-subtle bg-canvas px-md text-base text-primary placeholder:text-muted focus:outline-none focus:ring-2 phone:h-11;
}

.key-input:focus {
  border-color: var(--ui-action);
  --tw-ring-color: color-mix(in srgb, var(--ui-action) 20%, transparent);
}

.key-error {
  @apply rounded-input border px-md py-sm text-tiny font-medium;
  border-color: color-mix(in srgb, var(--ui-neg) 30%, transparent);
  background-color: color-mix(in srgb, var(--ui-neg) 10%, transparent);
  color: var(--ui-neg);
}

.key-button {
  @apply inline-flex h-10 w-full items-center justify-center rounded-btn text-base font-semibold text-white shadow-soft transition disabled:cursor-not-allowed disabled:opacity-50 phone:h-11;
  background-color: var(--ui-action);
}

.key-button:hover:not(:disabled) {
  background-color: var(--ui-action-hover);
}
</style>
