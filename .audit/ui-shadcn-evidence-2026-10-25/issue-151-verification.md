# Issue #151 Verification

Base: `origin/main` at `f3480fa` (PR #149 merged)

## Checks

- `npm ci` completed from `frontend/`.
- `npm run lint` passed.
- `npm run typecheck` passed.
- `npm run test -- --run` passed: 22 files, 111 tests.
- `npm run build` passed and generated all seven current routes.
- Backend `/health` returned HTTP 200; the current frontend at `http://localhost:3500/login` returned HTTP 200.
- Existing Docker project `via-refactor-integration` services remain healthy; its older frontend container is stopped while the current worktree's dev server owns port 3500.

## Browser checks

- Checked the public shell at 1440x900 and 390x844.
- Selected Light, Dark, and System in turn; each remained selected after a reload. System followed the browser's dark system preference.
- The shell tests verify mobile navigation opens, Escape closes it, focus returns to the trigger, and auth routes do not show private navigation.
- Skip-link destinations are programmatically focusable on public and authenticated routes.
- Navigation tests verify active route matching and links only to current routes.

## Evidence

- Baseline screenshots: `.audit/ui-shadcn-baseline-2026-10-25/`
- Rebuilt public shell at 1440x900: `foundation-login-desktop.png`
- Rebuilt public shell at 390x844: `foundation-login-mobile.png`

The direct UI dependencies were checked locally: Radix UI, `clsx`, `cmdk`, `next-themes`, and `tailwind-merge` are MIT; `class-variance-authority` is Apache-2.0. The shadcn/ui MIT notice is recorded in `frontend/src/components/ui/LICENSE.md`.
