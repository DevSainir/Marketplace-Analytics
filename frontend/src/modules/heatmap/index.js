/**
 * PUBLIC API CONTRACT — heatmap module.
 *
 * «Тепловая карта»: every article of a workspace, day by day, painted by one
 * metric — the view for a workspace with too many working articles to watch one
 * at a time. Lives at /heatmap.
 *
 * The ONLY entry point other parts of the app may import from.
 */
export { heatmapRoutes } from '@/modules/heatmap/routes'

// «Группы» are the heatmap's by birth and every filtered page's by use: the
// P&L, the balance and advertising filter by them with the same menu, and a
// group made on any of them is in all of them.
export { default as GroupsFilter } from '@/modules/heatmap/components/GroupsFilter.vue'
export {
  UNGROUPED,
  UNNAMED,
  articlesOfGroups,
  splitBy,
  useGroupCut,
  useGroupsStore,
} from '@/modules/heatmap/groupsStore'
