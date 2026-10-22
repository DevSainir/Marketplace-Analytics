import { createPinia } from 'pinia'
import PrimeVue from 'primevue/config'
import { createApp } from 'vue'

import App from '@/App.vue'
import '@/assets/main.css'
// `ui-next` — the app's design system, and the only one: `tokens.css` defines
// every colour, shadow and radius, and `tailwind.config.js` resolves to it.
// Loaded AFTER main.css so its component rules win on source order. These are
// not optional — without them the tokens are undefined.
import '@/core/styles/ui-next/tokens.css'
import '@/core/styles/ui-next/components.css'
import '@/core/styles/ui-next/skin.css'
import router from '@/core/router'
import { installStaleAssetReload } from '@/core/router/staleAssets'
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

// Last: it records the target of each navigation, after the guards above
// have had their say, so a reload for stale assets lands where the person
// was going.
installStaleAssetReload(router)

app.mount('#app')
