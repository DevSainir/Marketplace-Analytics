<script setup>
/**
 * «Безопасность» — the two things an account holder controls about their own
 * access, both of which the product used to only half-offer.
 *
 * The password button mailed a reset code and left nowhere to type it, so the
 * flow could not be completed. It now runs on the endpoint built for a
 * signed-in caller: current password in, no code, other devices out.
 *
 * Sessions had one lever, «выйти отовсюду» — the right thing to reach for once
 * you know something is wrong, and no help at all in finding out. The list is
 * the half that was missing.
 */
import { onMounted, ref } from 'vue'

import { extractErrorMessage } from '@/core/api/axios'
import PasswordForm from '@/modules/profile/components/PasswordForm.vue'
import SessionList from '@/modules/profile/components/SessionList.vue'
import { changePassword, endSession, fetchSessions } from '@/modules/profile/api'

const sessions = ref([])
const sessionsLoading = ref(true)
/** A family_id being ended, or 'all'. */
const ending = ref(null)

const passwordForm = ref(null)
const changing = ref(false)
const passwordError = ref('')

async function loadSessions() {
  sessionsLoading.value = true
  try {
    sessions.value = await fetchSessions()
  } catch {
    sessions.value = []
  } finally {
    sessionsLoading.value = false
  }
}

onMounted(loadSessions)

async function onChangePassword(payload) {
  changing.value = true
  passwordError.value = ''
  try {
    await changePassword(payload)
    passwordForm.value?.reset()
    // The other devices are gone server-side; the list has to agree.
    await loadSessions()
  } catch (err) {
    passwordError.value = extractErrorMessage(err)
  } finally {
    changing.value = false
  }
}

async function onEndSession(familyId) {
  ending.value = familyId
  try {
    await endSession(familyId)
    await loadSessions()
  } finally {
    ending.value = null
  }
}

async function onEndOthers() {
  ending.value = 'all'
  try {
    // One request per session rather than the account-wide lever: that one
    // ends THIS browser too, and «завершить все другие» must not sign out the
    // person pressing it.
    const others = sessions.value.filter((session) => !session.is_current)
    for (const session of others) {
      await endSession(session.family_id)
    }
    await loadSessions()
  } finally {
    ending.value = null
  }
}
</script>

<template>
  <div class="pf-section">
    <div class="pf-panel">
      <header class="pf-panel__head">
        <div class="min-w-0">
          <h2 class="pf-panel__title">Пароль</h2>
        </div>
      </header>

      <PasswordForm
        ref="passwordForm"
        :saving="changing"
        :error="passwordError"
        @submit="onChangePassword"
        @clear-error="passwordError = ''"
      />
    </div>

    <div class="pf-panel">
      <header class="pf-panel__head">
        <div class="min-w-0">
          <h2 class="pf-panel__title">Активные сеансы</h2>
          <p class="pf-panel__note">Каждый браузер, в котором выполнен вход в этот аккаунт.</p>
        </div>
      </header>

      <SessionList
        :sessions="sessions"
        :loading="sessionsLoading"
        :busy="ending"
        @end="onEndSession"
        @end-others="onEndOthers"
      />
    </div>
  </div>
</template>
