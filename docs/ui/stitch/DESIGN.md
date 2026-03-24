# Design System Specification: Professional Matte Financial Intelligence

## 1. Overview & Creative North Star: "The Digital Oracle"
The Creative North Star for this design system is **The Digital Oracle**. In a world of volatile financial data, the UI must feel like a calm, authoritative source of truth. We move beyond the "SaaS-standard" boxy grid by embracing **Organic Tonal Depth**.

Instead of rigid lines, we use light and density to guide the eye. By utilizing intentional asymmetry—placing high-density data visualizations against expansive, breathing negative space—we create an editorial feel that mimics high-end financial broadsheets, reimagined for a glass-and-silicon era. The goal is a "Matte" finish: sophisticated, non-reflective, and profoundly premium.

---

## 2. Colors & Surface Philosophy
The palette is rooted in the depth of the night market, utilizing a "Deep Navy-Charcoal" foundation to allow the neon-laced Cyan primary to hum with energy.

### Core Palette (Material Design Tokens)
*   **Surface Foundation:** `surface` (#10131A) / `surface_container_lowest` (#0B0E14)
*   **The Primary Action:** `primary_container` (#00F2FF) — Use for critical path actions.
*   **The Signal Colors:**
    *   *Bullish:* `secondary` (#4EDE03)
    *   *Bearish:* `error` (#FFB4AB)
    *   *Warning:* `tertiary_fixed_dim` (#FFB95F)

### The "No-Line" Rule
**Borders are prohibited for structural sectioning.** To separate a sidebar from a main feed, or a header from a body, use a background shift. For example, a `surface_container_low` (#191C22) sidebar sitting flush against a `surface` (#10131A) main stage. Contrast is our architect, not lines.

### Surface Hierarchy & Nesting
Treat the dashboard as layers of frosted obsidian.
*   **Base:** `surface_container_lowest`
*   **Sectioning:** `surface_container_low`
*   **Interactive Cards:** `surface_container` or `surface_container_high`
*   **Nesting Rule:** When placing an element inside a card (like a data chip inside a stock module), the inner element must use a *lower* tier (e.g., `surface_container_low` inside a `surface_container_high` card) to create a "recessed" or "etched" look.

### The "Glass & Gradient" Rule
Floating modals and high-level AI insights must use **Glassmorphism**.
*   **Formula:** `surface_container_highest` at 60% opacity + `backdrop-blur: 20px`.
*   **Signature Textures:** For Primary CTAs, use a linear gradient from `primary` (#E1FDFF) to `primary_container` (#00F2FF) at a 135-degree angle to provide a metallic, high-fidelity sheen.

---

## 3. Typography: Editorial Authority
We utilize a dual-font strategy to balance human-centric readability with data-driven precision.

*   **Display & Headlines (Manrope):** Use Manrope for all `display-` and `headline-` tokens. Its geometric but slightly rounded nature feels modern and bespoke.
*   **Body & Interface (Inter):** Use Inter for all `title-`, `body-`, and `label-` tokens.
*   **The Financial Rule:** All numerical data, tickers, and percentages **must** use `font-variant-numeric: tabular-nums`. This prevents the "jumping" of numbers during real-time updates and ensures vertical alignment in tables.

**Hierarchy Note:** Maintain a high contrast between `headline-lg` (2rem) and `body-md` (0.875rem). The vast difference in scale creates the "Editorial" look characteristic of premium financial reports.

---

## 4. Elevation & Depth: Tonal Layering
Traditional drop shadows are too "web-standard." We use **Ambient Shadows** and **Tonal Lift**.

*   **The Layering Principle:** Depth is achieved by "stacking" the surface-container tiers. A `surface_container_highest` card on a `surface` background provides enough contrast to signify elevation without a single pixel of shadow.
*   **Ambient Shadows:** For floating elements (Modals/Popovers), use: `box-shadow: 0 24px 48px -12px rgba(0, 0, 0, 0.5)`. The shadow must be large, diffused, and feel like it is absorbing the light of the background.
*   **The "Ghost Border" Fallback:** If accessibility requires a container edge (e.g., in high-glare environments), use a `outline_variant` (#3A494B) at 15% opacity. It should be felt, not seen.

---

## 5. Signature Components

### Primary Buttons
*   **Style:** `primary_container` (#00F2FF) background with `on_primary` (#00363A) text.
*   **Shape:** `md` (0.375rem) radius for a "precision instrument" feel.
*   **State:** Hover triggers a slight glow using a 10px blur of the primary color.

### Financial Cards
*   **Rule:** Forbid divider lines. Separate the "Ticker Header" from the "Price Body" using a `2.5` (0.5rem) spacing gap or a subtle shift from `surface_container` to `surface_container_low`.
*   **Sparklines:** Use `primary` for neutral trends, `secondary` for bullish, and `error` for bearish. Line weight: 1.5px.

### Steppers (Process Tracking)
*   **Visual:** Do not use circles with numbers. Use 2px thick horizontal bars.
*   **Active:** `primary_container`.
*   **Inactive:** `surface_variant` at 30% opacity. This creates a "filmstrip" aesthetic.

### Input Fields
*   **Style:** Minimalist. No background fill; only a bottom "Ghost Border" using `outline_variant`.
*   **Focus State:** A 2px solid `primary_container` (#00F2FF) bottom border with a 4px soft outer glow.

---

## 6. Do’s and Don’ts

### Do
*   **DO** use whitespace as a separator. If you think you need a line, try adding `6` (1.3rem) of spacing instead.
*   **DO** use `tabular-nums` for every single digit on the screen.
*   **DO** ensure all interactive elements have a focus state of 2px solid Cyan for accessibility.
*   **DO** use "surface-nesting" to create depth in complex data modules.

### Don’t
*   **DON'T** use pure black (#000000) or pure white (#FFFFFF). Stick to the tokenized neutrals to maintain the "Matte" finish.
*   **DON'T** use 100% opaque borders. They break the illusion of the "Digital Oracle" glass layers.
*   **DON'T** use standard "Drop Shadows" from a UI kit. Shadows must be ambient, wide, and dark.
*   **DON'T** clutter the dashboard. If a data point isn't actionable, move it to a `surface_container_lowest` "Details" pane.

---

## 7. Spacing Scale
The spacing scale is built on a tight 0.1rem-0.2rem increment system to allow for the extreme precision required in financial dashboards.

*   **Micro (0.5 - 2):** Use for internal component padding (e.g., inside a chip).
*   **Moderate (3 - 6):** Use for spacing between related data points.
*   **Macro (10 - 24):** Use for layout margins and separating major dashboard widgets.
