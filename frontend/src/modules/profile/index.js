/**
 * PUBLIC API CONTRACT — profile module.
 *
 * The ONLY entry point other parts of the app may import from. Everything not
 * re-exported here (api.js, views, components) is module-private; deep imports
 * are fatal ESLint errors.
 */
export { profileRoutes } from '@/modules/profile/routes'
export { useWorkspaceStore } from '@/modules/profile/store'
export { installWorkspaceGuard, installInternalGuard } from '@/modules/profile/guard'
export { useMembersStore } from '@/modules/profile/membersStore'
export { default as ActivationGate } from '@/modules/profile/components/ActivationGate.vue'
export { default as BackfillNotice } from '@/modules/profile/components/BackfillNotice.vue'
