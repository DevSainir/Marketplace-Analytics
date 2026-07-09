import { createPinia } from 'pinia'
import PrimeVue from 'primevue/config'
import { createApp } from 'vue'

import App from '@/App.vue'
import '@/assets/main.css'
import router from '@/core/router'
import { installAuthGuard } from '@/modules/auth'

const app = createApp(App)

app.use(createPinia())
app.use(router)
// PrimeVue in unstyled mode: component architecture (sorting, pagination,
// sticky headers) with our own Tailwind design tokens on top.
app.use(PrimeVue, { unstyled: true })

// Session bootstrap + requiresAuth/guestOnly gating + 401 handling.
// Installed here (not in core/router) so core stays module-agnostic.
installAuthGuard(router)

app.mount('#app')
