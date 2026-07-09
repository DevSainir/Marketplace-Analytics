# Frontend Design System & Backend Integration Guidelines

## 1. UI/UX Aesthetics & Design System
* **Overall Style:** Vercel / Tailwind UI aesthetics. Clean, professional, minimal, and strict B2B focus.
* **Color Palette (Tailwind Classes):**
    * Backgrounds: `bg-slate-50` for the main app background.
    * Surfaces: `bg-white` for cards, modals, and dropdowns.
    * Borders: `border-slate-200` for subtle separation.
    * Primary Text: `text-slate-900` for headings, `text-slate-500` for secondary text/labels.
    * Primary Brand Accent: `indigo-600` (buttons, active states, important links).
    * Status Colors: `emerald-500` (success/profit), `rose-500` (errors/loss), `amber-500` (warnings/OOS).
* **Typography:** Default Tailwind sans-serif font stack (Inter). Strict adherence to readable spacing.
* **Layouts:** Use CSS Grid for metric cards (`grid-cols-1 md:grid-cols-3 lg:grid-cols-4`). Use Flexbox for alignments. Apply `shadow-sm` and `rounded-xl` for standard card components.

## 2. Component Libraries Strategy
Do not invent complex components from scratch. Follow this strict distribution:
1. **Shadcn-vue (Copy-Paste Component Approach):** Use this as the primary reference for basic UI elements (Buttons, Input fields, Cards, Dialogs, Select menus). Simulate Shadcn-vue's clean styling in standard Tailwind classes.
2. **PrimeVue (Tailwind Unstyled Mode):** STRICTLY use PrimeVue for complex data visualization, specifically the `DataTable` component. The analytics tables must support sorting, sticky headers, and pagination out of the box using PrimeVue's architecture.
