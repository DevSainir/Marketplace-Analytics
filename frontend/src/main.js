import { createPinia } from 'pinia'
import PrimeVue from 'primevue/config'
import { createApp } from 'vue'

import App from '@/App.vue'
import '@/assets/main.css'
import router from '@/core/router'
import { installAuthGuard } from '@/modules/auth'
import { installWorkspaceGuard } from '@/modules/profile'

const app = createApp(App)

app.use(createPinia())
app.use(router)
// PrimeVue in unstyled mode: component architecture (sorting, pagination,
// sticky headers) with our own Tailwind design tokens on top.
app.use(PrimeVue, { unstyled: true })

// Session bootstrap + requiresAuth/guestOnly gating + 401 handling.
// Installed here (not in core/router) so core stays module-agnostic.
installAuthGuard(router)
// Workspace context (X-Workspace-Id) resolved before any authenticated view
// fires its first API call. Must come AFTER the auth guard (needs a session).
installWorkspaceGuard(router)

// A deploy replaces every asset with a freshly hashed name, so a tab that has
// been open across one asks for chunks that no longer exist and dies on the next
// lazy route — which reads as "the site logged me out and broke". One reload
// fixes it, and the guard makes sure a genuinely broken build cannot turn that
// into an infinite reload loop.
const RELOADED_FOR_STALE_ASSETS = 'reloaded-for-stale-assets'

function reloadOnceForStaleAssets() {
  if (sessionStorage.getItem(RELOADED_FOR_STALE_ASSETS)) return
  sessionStorage.setItem(RELOADED_FOR_STALE_ASSETS, '1')
  window.location.reload()
}

window.addEventListener('vite:preloadError', (event) => {
  event.preventDefault()
  reloadOnceForStaleAssets()
})

router.onError((error) => {
  if (
    /dynamically imported module|Importing a module script failed|Failed to fetch/i.test(
      String(error?.message),
    )
  ) {
    reloadOnceForStaleAssets()
  }
})

// Cleared on a successful navigation: the next deploy gets its own single reload.
router.afterEach(() => sessionStorage.removeItem(RELOADED_FOR_STALE_ASSETS))

app.mount('#app')
