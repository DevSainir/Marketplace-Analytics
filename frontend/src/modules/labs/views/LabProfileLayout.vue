<script setup>
/**
 * DESIGN SANDBOX — the profile, as a section rather than a page.
 *
 * Runs on REAL data: the same stores, the same endpoints, the same writes as
 * `/profile`. Only the shape is new, so what is being compared is the shape.
 *
 * **Why three routes now, when the first version deliberately had none.** That
 * version was right about what it had: four short blocks, «чуть больше экрана
 * высоты», and splitting that into four screens would have bought navigation
 * and sold four near-empty pages. What changed is the content — a real
 * security section (password, and every device this account is signed in on)
 * and a team page that now also carries the outstanding invitations and the
 * access log. Three screens under one scrollbar is a page you scroll past
 * rather than one you navigate.
 *
 * This shell owns only what all three share: the account identity, the rail,
 * and the one bootstrap. Each page owns its own data and its own drawers.
 */
import { computed, onMounted } from 'vue'
import { RouterView } from 'vue-router'

import ProfileNav from '@/modules/labs/components/profile/ProfileNav.vue'
import { useLabTeam } from '@/modules/labs/labTeam'
import { useMembersStore, useWorkspaceStore } from '@/modules/profile'

import '@/core/styles/ui-next/tokens.css'
import '@/core/styles/ui-next/components.css'
import '@/core/styles/ui-next/skin.css'
import '@/modules/labs/views/LabProfileView.css'

const store = useWorkspaceStore()
const members = useMembersStore()
const team = useLabTeam()

const ROLE_LABELS = {
  dev: 'Разработчик',
  owner: 'Владелец',
  manager: 'Менеджер',
  user: 'Без компании',
}

const SECTIONS = [
  { name: 'labs-profile-general', label: 'Общие', hint: 'Аккаунт и кабинеты' },
  { name: 'labs-profile-team', label: 'Команда', hint: 'Менеджеры и доступ' },
  { name: 'labs-profile-security', label: 'Безопасность', hint: 'Пароль и устройства' },
]

/** Only the sections this account can actually be shown. */
const sections = computed(() =>
  SECTIONS.filter((section) => section.name !== 'labs-profile-team' || team.available.value),
)

onMounted(async () => {
  await store.ensureLoaded().catch(() => {})
  await members.ensureLoaded()
  await team.load()
})
</script>

<template>
  <div class="app-container py-lg">
    <div class="lp-layout">
      <aside class="lp-aside">
        <ProfileNav
          :email="store.me?.email ?? ''"
          :role-label="ROLE_LABELS[members.role] ?? ''"
          :sections="sections"
        />
      </aside>

      <main class="lp-main">
        <p v-if="store.error || members.error" class="lp-alert">
          {{ store.error || members.error }}
        </p>

        <section v-if="!members.hasOrganization" class="lp-alert lp-alert--soft">
          Аккаунт ещё не привязан к компании. Ключ активации вводится на обычной странице профиля —
          этот макет только показывает раскладку.
        </section>

        <RouterView />
      </main>
    </div>
  </div>
</template>
