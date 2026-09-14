<script setup>
/**
 * «Безопасность» — the two levers an account holder has over their own access.
 *
 * Neither was on the old profile page. There is still no «сменить пароль»
 * endpoint for a signed-in user: the backend has `/password-reset/request` and
 * `/password-reset/confirm`, both keyed on a mailed code, so the honest button
 * is «пришлите код» rather than a password form that cannot be submitted.
 *
 * `logout-all` has existed since the incident-response work and had no caller
 * outside the tests. It is the one lever that stops tokens already handed out,
 * and it ends THIS session too — hence the two-press confirm.
 */
import { ref } from 'vue'

defineProps({
  email: { type: String, default: '' },
  /** 'password' | 'sessions' | null */
  busy: { type: [String, null], default: null },
  /** Set after a reset code was mailed, so the button can say so. */
  codeSent: { type: Boolean, default: false },
})

const emit = defineEmits(['change-password', 'revoke-sessions'])

const arming = ref(false)

function onRevoke() {
  if (!arming.value) {
    arming.value = true
    setTimeout(() => (arming.value = false), 4000)
    return
  }
  arming.value = false
  emit('revoke-sessions')
}
</script>

<template>
  <div class="lp-split">
    <section class="lp-card">
      <h3 class="lp-card__title">Пароль</h3>
      <p class="lp-card__note">
        Пароль меняется через письмо: мы пришлём код на {{ email || 'вашу почту' }}, и на следующем
        шаге вы зададите новый. Отдельной формы «старый пароль → новый» у сервиса нет.
      </p>
      <div class="lp-card__foot">
        <button
          type="button"
          class="lp-btn lp-btn--primary"
          :disabled="busy === 'password'"
          @click="emit('change-password')"
        >
          {{ busy === 'password' ? 'Отправляем…' : 'Прислать код' }}
        </button>
        <span v-if="codeSent" class="lp-ok">Код отправлен — проверьте почту.</span>
      </div>
    </section>

    <section class="lp-card">
      <h3 class="lp-card__title">Сессии</h3>
      <p class="lp-card__note">
        Завершает вход на всех устройствах сразу — на телефоне, на чужом компьютере, везде. Текущая
        вкладка тоже выйдет, войти нужно будет заново.
      </p>
      <div class="lp-card__foot">
        <button
          type="button"
          class="lp-btn lp-btn--danger"
          :class="arming ? 'is-armed' : ''"
          :disabled="busy === 'sessions'"
          @click="onRevoke"
        >
          {{ arming ? 'Точно выйти везде?' : 'Выйти со всех устройств' }}
        </button>
      </div>
    </section>
  </div>
</template>

<style scoped>
.lp-split {
  @apply grid gap-md;
  grid-template-columns: repeat(auto-fit, minmax(20rem, 1fr));
}

.lp-card {
  @apply flex flex-col gap-sm rounded-card px-lg py-md;
  background: var(--ui-surface);
  box-shadow: var(--ui-sh-xs);
}

.lp-card__title {
  @apply text-h3 font-semibold text-primary;
}

.lp-card__note {
  @apply flex-1 text-tiny font-medium;
  color: var(--ui-muted);
}

.lp-card__foot {
  @apply mt-xs flex flex-wrap items-center gap-sm;
}

.lp-ok {
  @apply text-tiny font-semibold;
  color: var(--ui-pos);
}
</style>
