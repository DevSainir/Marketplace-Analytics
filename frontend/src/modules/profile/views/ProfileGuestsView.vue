<script setup>
/**
 * «Доступы» — which workspaces of other companies are open to whom. Dev only.
 *
 * A grant opens one workspace, read-only, to one account by its email: every
 * section, no writes. The account needs no company of its own — that is what
 * lets a dev show a workspace to anybody who has registered. Closing a grant
 * takes it away on the next request.
 *
 * The rail hides this page from everyone but a dev, and the API refuses them
 * (`DevAccess`), so a non-dev who types the address sees a refusal rather than
 * an empty form whose every request answers 403.
 */
import { computed, onMounted, ref } from 'vue'

import { extractErrorMessage } from '@/core/api/axios'
import DataState from '@/core/components/DataState.vue'
import {
  fetchGrantableWorkspaces,
  fetchGuestGrants,
  grantGuest,
  revokeGuest,
} from '@/modules/profile/api'
import { useMembersStore } from '@/modules/profile/membersStore'
import { formatMoscow } from '@/core/utils/moscow'

const members = useMembersStore()
const isDev = computed(() => members.role === 'dev')

const grants = ref([])
const workspaces = ref([])
const loading = ref(true)
const loadError = ref('')

const email = ref('')
const workspaceName = ref('')
const saving = ref(false)
const formError = ref('')
/** The id of a grant being closed. */
const revoking = ref(null)

const canSubmit = computed(
  () => email.value.trim().length >= 3 && workspaceName.value !== '' && !saving.value,
)

async function load() {
  loading.value = true
  loadError.value = ''
  try {
    const [grantList, workspaceList] = await Promise.all([
      fetchGuestGrants(),
      fetchGrantableWorkspaces(),
    ])
    grants.value = grantList
    workspaces.value = workspaceList
  } catch (err) {
    loadError.value = extractErrorMessage(err)
  } finally {
    loading.value = false
  }
}

onMounted(async () => {
  await members.ensureLoaded()
  if (isDev.value) await load()
})

async function submit() {
  if (!canSubmit.value) return
  saving.value = true
  formError.value = ''
  try {
    await grantGuest({ email: email.value.trim(), workspaceName: workspaceName.value })
    email.value = ''
    grants.value = await fetchGuestGrants()
  } catch (err) {
    formError.value = extractErrorMessage(err)
  } finally {
    saving.value = false
  }
}

async function revoke(grantId) {
  revoking.value = grantId
  formError.value = ''
  try {
    await revokeGuest(grantId)
    grants.value = grants.value.filter((grant) => grant.id !== grantId)
  } catch (err) {
    formError.value = extractErrorMessage(err)
  } finally {
    revoking.value = null
  }
}

function grantedOn(iso) {
  return formatMoscow(iso, {
    day: 'numeric',
    month: 'long',
    year: 'numeric',
  })
}
</script>

<template>
  <div class="pf-section">
    <p v-if="members.role && !isDev" class="pf-empty">Раздел доступен только разработчику.</p>

    <template v-else-if="isDev">
      <div class="pf-panel">
        <header class="pf-panel__head">
          <div class="min-w-0">
            <h2 class="pf-panel__title">Открыть кабинет</h2>
            <p class="pf-panel__note">
              Человек увидит все разделы кабинета, но ничего не сможет изменить. Своя компания ему
              не нужна — достаточно зарегистрироваться.
            </p>
          </div>
        </header>

        <form class="guests-form" @submit.prevent="submit">
          <label class="guests-form__field">
            <span class="guests-label">Почта</span>
            <input
              v-model="email"
              type="email"
              maxlength="320"
              required
              placeholder="name@example.com"
              autocomplete="off"
              class="ui-input w-full"
            />
          </label>
          <label class="guests-form__field">
            <span class="guests-label">Кабинет</span>
            <select v-model="workspaceName" required class="ui-select w-full">
              <option value="" disabled>Выберите кабинет</option>
              <option v-for="ws in workspaces" :key="ws.id" :value="ws.name">{{ ws.name }}</option>
            </select>
          </label>
          <button type="submit" class="ui-btn ui-btn--primary" :disabled="!canSubmit">
            {{ saving ? 'Открываем…' : 'Открыть доступ' }}
          </button>
        </form>

        <p v-if="formError" class="pf-alert">{{ formError }}</p>
      </div>

      <div class="pf-panel">
        <header class="pf-panel__head">
          <div class="min-w-0">
            <h2 class="pf-panel__title">Открытые доступы</h2>
          </div>
        </header>

        <DataState v-if="loading" kind="loading" />
        <DataState v-else-if="loadError" kind="error" :text="loadError" />
        <p v-else-if="!grants.length" class="pf-empty">Пока никому не открыт ни один кабинет.</p>

        <div v-else class="pf-grid">
          <div class="pf-grid__head guests-cols">
            <span>Кто</span>
            <span>Кабинет</span>
            <span />
          </div>
          <article v-for="grant in grants" :key="grant.id" class="pf-grid__row guests-cols">
            <span class="pf-cell pf-cell--who">
              <span class="pf-who__mail" :title="grant.email">{{ grant.email }}</span>
              <span class="pf-who__meta">с {{ grantedOn(grant.created_at) }}</span>
            </span>
            <span class="pf-cell">
              <span class="ui-badge is-soft">{{ grant.workspace_name }}</span>
            </span>
            <span class="pf-cell pf-cell--act">
              <button
                type="button"
                class="ui-btn ui-btn--danger ui-btn--sm"
                :disabled="revoking === grant.id"
                @click="revoke(grant.id)"
              >
                {{ revoking === grant.id ? 'Закрываем…' : 'Закрыть' }}
              </button>
            </span>
          </article>
        </div>
      </div>
    </template>
  </div>
</template>

<style scoped>
.guests-label {
  @apply text-tiny font-semibold uppercase tracking-wide;
  color: var(--ui-faint);
}

.guests-form {
  @apply flex items-end gap-md;
}

.guests-form__field {
  @apply flex min-w-0 flex-1 flex-col gap-xs;
}

.guests-cols {
  grid-template-columns: minmax(0, 2fr) minmax(0, 1fr) auto;
}

@media (max-width: 430px) {
  .guests-form {
    @apply flex-col items-stretch;
  }

  .guests-cols {
    grid-template-columns: minmax(0, 1fr) auto;
  }

  .pf-grid__head.guests-cols {
    display: none;
  }

  .guests-cols .pf-cell--who {
    grid-column: 1 / -1;
  }
}
</style>
