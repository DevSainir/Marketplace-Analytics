<script setup>
/**
 * Inviting a manager, with their access chosen up front.
 *
 * The grant is part of the invitation rather than something applied after the
 * person joins: between joining and being narrowed there would be a window
 * with real access in it, and nobody watching.
 *
 * The token is shown exactly once — the server stores only its hash — so the
 * link stays on screen until the owner dismisses it.
 */
import { computed, ref } from 'vue'

import AccessGrantFields from '@/modules/profile/components/AccessGrantFields.vue'
import { MODULES } from '@/modules/profile/membersStore'

defineProps({ saving: { type: String, default: null } })
const emit = defineEmits(['invite'])

const email = ref('')
// An hour by default. The link is reusable until it expires, so the window is
// what bounds it — a week-long one that got out is a week-long open door.
const validForHours = ref(1)
const grant = ref({ accessLevel: 'read_write', modules: MODULES.map((m) => m.key) })
const issued = ref(null)
const copied = ref(false)

// The value the server returns is an opaque token, and it used to be shown as
// one under the word «ссылка» — which was both untrue and unusable: there was
// nowhere to put a bare token. It is a link now, pointing at the screen that
// redeems it.
const inviteLink = computed(() =>
  issued.value
    ? `${window.location.origin}/invite?token=${encodeURIComponent(issued.value.token)}`
    : '',
)

async function copyLink() {
  try {
    await navigator.clipboard.writeText(inviteLink.value)
    copied.value = true
  } catch {
    // Clipboard access is refused in some browsers and over plain HTTP. The
    // link is on screen and selectable either way, so this only loses the
    // convenience.
  }
}

function onSubmit() {
  emit('invite', {
    email: email.value.trim() || null,
    validForHours: validForHours.value,
    accessLevel: grant.value.accessLevel,
    modules: grant.value.modules,
    onIssued: (invitation) => {
      issued.value = invitation
      email.value = ''
    },
  })
}
</script>

<template>
  <section class="rounded-card border border-border-subtle bg-surface p-lg shadow-card">
    <h2 class="text-h2 font-bold text-primary">Пригласить менеджера</h2>
    <p class="mt-xs text-tiny font-medium text-muted">
      Доступ выдаётся сразу — менеджер входит уже с этими правами.
    </p>

    <form class="mt-md flex flex-col gap-md" @submit.prevent="onSubmit">
      <label class="flex flex-col gap-xs">
        <span class="text-tiny font-medium text-muted">Email (необязательно)</span>
        <input
          v-model="email"
          type="email"
          placeholder="Оставьте пустым, чтобы получить ссылку"
          class="rounded-btn border border-border-subtle bg-surface px-sm py-xs text-base text-primary"
        />
      </label>

      <label class="flex flex-col gap-xs">
        <span class="text-tiny font-medium text-muted">Ссылка действует, часов</span>
        <input
          v-model.number="validForHours"
          type="number"
          min="1"
          max="720"
          class="w-28 rounded-btn border border-border-subtle bg-surface px-sm py-xs text-base text-primary"
        />
      </label>

      <AccessGrantFields
        :access-level="grant.accessLevel"
        :modules="grant.modules"
        :disabled="saving === 'invite'"
        @update="(next) => (grant = next)"
      />

      <div class="flex justify-end">
        <button
          type="submit"
          class="rounded-btn bg-action px-md py-xs text-base font-semibold text-white transition-opacity disabled:opacity-50"
          :disabled="saving === 'invite'"
        >
          {{ saving === 'invite' ? 'Создаём…' : 'Пригласить' }}
        </button>
      </div>
    </form>

    <div v-if="issued" class="mt-md rounded-card border border-action/30 bg-action/5 p-md">
      <p class="text-tiny font-medium text-muted">
        Ссылка показывается один раз — скопируйте и отправьте её приглашённому. Пока она действует,
        по ней может присоединиться любой, у кого она есть.
      </p>
      <code class="mt-xs block break-all text-base font-medium text-primary">
        {{ inviteLink }}
      </code>
      <button type="button" class="mt-xs text-tiny font-semibold text-action" @click="copyLink">
        {{ copied ? 'Скопировано' : 'Скопировать ссылку' }}
      </button>
      <button
        type="button"
        class="mt-sm text-tiny font-semibold text-action"
        @click="issued = null"
      >
        Скрыть
      </button>
    </div>
  </section>
</template>
