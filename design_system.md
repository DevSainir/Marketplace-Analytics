# UI Architecture & Design System Rules

You are an expert Frontend Architect. All generated UI code must strictly adhere to the project's design system.

## 1. Design System Configuration
Use these tokens for all styling. Never use arbitrary values (like `h-[123px]` or `bg-[#123123]`) if a token exists.

```javascript
// tailwind.config.js - Use these for reference
colors: {
  bg: { canvas: '#E8E8E8', surface: '#F1F1F1' },
  text: { primary: '#101010', muted: '#858585' },
  status: { positive: '#179E60', negative: '#EE522B', warning: '#E8814F' },
  action: { DEFAULT: '#007E76', hover: '#17B2A8' },
  border: { subtle: '#E0E0E0' },
},
fontFamily: { sans: ['Inter Tight', 'sans-serif'] },
fontWeight: { body: '400', medium: '500', semibold: '600', bold: '700' },
spacing: { xs: '4px', sm: '8px', md: '16px', lg: '24px', xl: '32px' },
borderRadius: { btn: '6px', card: '12px', input: '8px' },
boxShadow: {
  soft: '0 1px 3px 0 rgba(0, 0, 0, 0.1), 0 1px 2px -1px rgba(0, 0, 0, 0.1)',
  card: '0 4px 6px -1px rgba(0, 0, 0, 0.05), 0 2px 4px -2px rgba(0, 0, 0, 0.05)'
},
fontSize: { tiny: '0.75rem', base: '0.875rem', h3: '1rem', h2: '1.25rem' }
```

## 2. Component Libraries Strategy
Do not invent complex components from scratch. Follow this strict distribution:
1. **Shadcn-vue (Copy-Paste Component Approach):** Use this as the primary reference for basic UI elements (Buttons, Input fields, Cards, Dialogs, Select menus). Simulate Shadcn-vue's clean styling in standard Tailwind classes.
2. **PrimeVue (Tailwind Unstyled Mode):** STRICTLY use PrimeVue for complex data visualization, specifically the `DataTable` component. The analytics tables must support sorting, sticky headers, and pagination out of the box using PrimeVue's architecture.

## 3. Component Guidelines
* **Semantic Styling:** Always use semantic class names (e.g., text-primary, bg-surface, border-border-subtle).

* **Typography Hierarchy:**

* * **KPI & Main Titles:** text-h2 font-bold text-primary

* * **Labels/Descriptions:** text-tiny font-medium text-muted

* * **Body/Data:** text-base font-body text-primary

* **Card Structure:** Every main block (table, widget) must use: bg-surface border border-border-subtle rounded-card shadow-card.

* **Spacing:** Use internal padding p-lg (24px) for content containers.

* **Atomic Structure:**

* * **src/core/components/** -> Dumb, reusable atoms (Buttons, Inputs, Pickers).

* * **src/modules/some_module/components/** -> Domain-specific molecules (Tables, Widgets).

* * **views/** -> Page-level composition using v-if for state transitions.

## 4. Development Flow
* Before coding, check if a suitable component already exists in core.

* If creating a new component, prioritize layout using flex or grid before adding content.

* Always provide clean, modular Vue 3 Composition API code.
