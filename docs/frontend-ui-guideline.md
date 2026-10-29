# Frontend UI design guide

Status: Canonical visual and interaction supplement for [`frontend-guideline.md`](frontend-guideline.md).
Scope: `frontend/`

This guide defines the visual system and component-source policy for the financial research workspace. It complements the frontend architecture guide and does not define backend contracts.

## Product direction

- Use a precise, calm financial-workspace style: dense enough for repeated analysis, with clear hierarchy for reports, evidence, status, and decisions.
- Prefer compact, aligned information over oversized headings or decorative cards. Keep sections unframed unless a repeated item or focused tool needs a border.
- Use color to reinforce meaning. Pair market direction, risk, and workflow status with labels or values; never rely on color alone.
- Use tabular numerals for prices, percentages, dates, and other comparable values. Keep charts, tables, and provenance readable at a glance.

## Tokens and typography

`frontend/src/app/globals.css` owns the semantic CSS variables for light and dark themes. `next-themes` provides system, light, and dark selection. Continue that token system instead of introducing page-specific color palettes.

- Use semantic tokens for background, surface, foreground, muted text, border, primary action, success, warning, error, chart increase, and chart decrease.
- Define a token before reusing a new visual meaning across features. Avoid raw color values and theme-name conditionals in feature components.
- Use the existing font roles: Manrope for headings, Inter for body text, and Geist Mono for fixed-width values. Keep numerical content tabular.
- Use a small, stable type scale: compact labels and metadata, readable body and data values, and restrained page headings. Reserve display-scale typography for a true product or marketing hero.
- Keep controls and repeated report surfaces at consistent dimensions and a compact radius. Do not let dynamic labels or loading states change their size.

## Component ownership

- Use the source-owned components in `frontend/src/components/ui/` as the shared primitive layer. The project follows the shadcn/ui component model and Lucide icons.
- Add only the primitives a feature uses. Keep financial-report composition, debate views, provenance, and workflow interactions in their owning feature.
- Use shadcn AI Elements as a reference or source for focused AI interaction patterns such as streamed messages, tool activity, citations, and confirmations. They do not own this product's workflow protocol or authorization.
- Do not add a second general-purpose UI runtime or a full-page template to obtain a component. Record the upstream source and retain required license notices when copying code.
- Reuse an existing primitive when it fits. Add a shared component only when multiple features need the same behavior.

## Workflow patterns

- Present agent work as explicit steps with stable status, ownership, and progress. Keep partial output, final reports, and human decisions visually distinct.
- Present debate output by round and speaker. Keep Bull, Bear, and Moderator contributions distinguishable, preserve their sequence, and place the final synthesis after the arguments it evaluates.
- Place a required human interaction inside its waiting activity or owning agent section. Keep it visible until backend confirmation; avoid modal interruption as the default.
- Make retry, cancel, approve, and reject states explicit. Disable duplicate actions while a request is pending and do not claim completion before the backend confirms it.
- Use brief transitions only when they clarify a state change. Respect reduced-motion preferences and avoid animation on every streamed token.

## Review

When changing a shared component or report surface, review its loading, empty, partial, error, and completed states, plus narrow and wide layouts. Check that text wraps without overlap and that data remains comparable. Review screenshots locally when useful; do not attach them to an issue unless requested.
