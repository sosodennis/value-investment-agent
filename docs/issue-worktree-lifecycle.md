# Issue and worktree lifecycle

Use one short-lived issue branch and worktree per active change. Send completed work to `main` through a pull request. Create a parent integration branch only when its child changes cannot be merged safely on their own. Issue hierarchy does not require branch hierarchy.

Keep issues open until their accepted change is on `main`. Use labels or project fields to show work in progress. Do not use a closed issue to mean "merged into an integration branch" or "ready for release".

## Deliver an issue to `main`

1. Define a user-visible outcome and testable acceptance criteria in the issue. Split unrelated outcomes into separate issues.
2. Fetch `origin` and create a short-lived issue branch and worktree from `origin/main`.
3. Keep the diff within the issue. Record a separate issue labeled `blocker` when the change exposes a gap in a shared contract, security boundary, ownership rule, or architecture. Do not hide the gap with a workaround.
4. Run the checks that cover the changed behavior. Inspect the full diff against the issue criteria.
5. Open a pull request targeting `main`. Link the issue. Use `Closes #<issue>` in the pull request description only when merging that pull request completes the issue's acceptance criteria.
6. Merge after the required checks and review pass. Run browser or service acceptance when the issue changes a user workflow or deployment behavior.
7. Verify the merge commit on `main`, record the evidence, and confirm GitHub closed the issue. Then remove the worktree and branch.

Use `Refs #<issue>` in commits and in pull requests that do not close the issue. Do not put `Closes`, `Fixes`, or `Resolves` in commits that may later reach `main` before the issue is complete. GitHub applies closing keywords in commit messages when those commits reach the default branch.

```sh
git fetch origin
git worktree add -b codex/issue-<id>-<short-name> ../value-investment-agent-issue-<id> origin/main
```

## Coordinate work that must land together

Use a parent integration branch only when intermediate child changes would break a shared contract, leave the product unusable, or fail required integration checks. First consider a feature flag, a compatible migration, or branch-by-abstraction so safe increments can land on `main`.

1. Give the parent one bounded outcome, final acceptance criteria, and linked GitHub sub-issues.
2. Create `codex/issue-<parent>-integration` from the latest `origin/main`. Use one dedicated integration worktree.
3. Record the integration branch, worktree path, Compose project name, child issues, acceptance commands, and cleanup plan in the parent issue.
4. Create each child branch from the current integration branch commit. Give each active child its own temporary worktree.
5. Open child pull requests against the integration branch. Link the child and parent issues. Use `Refs #<child>` and do not use a closing keyword.
6. Merge child pull requests serially. After each merge, update the integration worktree and run the checks affected by that change.
7. Mark each child `integrated` after its changes and child acceptance checks pass on the integration branch. Keep the child issue open. Record the child PR, integration commit, and check results.
8. Open the parent pull request to `main` as soon as it is useful for review. Keep it in draft while parent acceptance remains incomplete.
9. Refresh the integration branch from `origin/main`. Run parent acceptance against the resulting commit. Record the exact commit SHA and results.
10. Merge the parent pull request only after every child and parent acceptance criterion passes. Use closing keywords for the parent and all completed child issues in the PR description. Confirm that GitHub closed those issues.
11. Remove the integration worktree, local branch, and Compose project after confirming that the worktree has no uncommitted changes.

GitHub ignores closing keywords on pull requests that target a branch other than the default branch. Link integration pull requests to issues through GitHub's Development panel. Do not close child issues at integration time; the `integrated` label records that intermediate state.

Keep the integration branch short-lived. Synchronize it with `origin/main` at least once per workday and merge completed child pull requests promptly. If integration work lasts more than five working days, split it and land safe changes on `main`, or record a blocker with the remaining dependency and a revised integration plan.

```sh
git fetch origin
git worktree add -b codex/issue-<parent>-integration ../value-investment-agent-issue-<parent>-integration origin/main
git worktree add -b codex/issue-<child>-<short-name> ../value-investment-agent-issue-<child>-<short-name> codex/issue-<parent>-integration
```

## Keep parallel work safe

Start child branches from the latest integration commit, not from another child branch. Parallelize only when the changes do not overlap in files, APIs, schemas, migrations, or mutable test data. Merge pull requests serially. Update each child branch from the current integration branch and rerun affected checks before merging it.

Check out a branch in only one worktree at a time. Give every active worktree a unique Compose project name and unique published host ports. Include the repository and issue or worktree identifier in the project name. Do not start a full stack in every worktree unless the checks need it.

## Require evidence before merge

The pull request author records evidence that matches the change. Include:

- Issue number, pull request, source branch, target branch, and verified commit SHA.
- Exact commands run and their exit codes. Identify checks that did not run.
- Docker Compose project name and required service health for containerized acceptance.
- Browser route, viewport, actions, observed result, and relevant run or artifact identity for user workflow acceptance.
- Migration upgrade and recovery steps when the change alters persisted data.
- Known failures, degradation, and unverified criteria. Do not report partial acceptance as complete.

Run tests that exercise behavior at the layer that owns it. Run type checks, lint, contract checks, and security checks that cover the diff. Verify required Docker services are healthy. For browser workflows, exercise the real route and user action; mocked tests do not establish end-to-end behavior. Resolve blockers in their owning layer before marking work `VERIFIED`, merging it, or closing its issue.

Verify the exact commit that will merge. If the pull request changes after a check, rerun affected checks. Do not reuse evidence from an older commit. If a required acceptance criterion needs deployment, track deployment as a separate release or rollout issue unless deployment is explicitly part of the issue's outcome.

## Record one canonical runtime tuple

Every issue acceptance run must record one canonical runtime tuple and re-read it before every resume and before acceptance. The tuple is the join key between the GitHub issue, the exact commit, the Compose stacks, and the browser session. Do not infer any field from memory or from a stale browser tab.

Record these fields without secrets:

| Field | Required value |
| --- | --- |
| Worktree path | Absolute path used by the acceptance commands |
| Branch | Exact issue branch name |
| Verified implementation commit SHA | Exact implementation commit checked by the run; later commits may contain acceptance metadata only |
| Application Compose project | Explicit `docker compose -p` project name |
| Fundamental Compose project | Explicit project name, even when the app stack is separate |
| Compose files and overlays | Ordered `-f` list for each project |
| Env-file paths and SHA-256 | Exact `--env-file` paths plus a SHA-256 of each file, never their contents |
| Published host ports | Values reported by `docker compose ... port` |
| Application base URL | Derived from the current backend binding |
| Fundamental service URL | Derived from the current Fundamental binding |
| Browser session/tab identity | Fresh tab/session identifier for this runtime tuple |
| Preflight command and result | Command, exit code, and the exact commit it checked |
| Runtime-only overrides | Explicit relative paths allowed by `ALLOWED_UNTRACKED_PATHS`, never commit evidence |

For a typical two-stack acceptance, validate both configurations before starting services:

```sh
docker compose --env-file "$APP_ENV_FILE" -p "$APP_COMPOSE_PROJECT" \
  -f docker-compose.yml -f docker-compose.override.yml config --quiet
docker compose --env-file "$FUNDAMENTAL_ENV_FILE" -p "$FUNDAMENTAL_COMPOSE_PROJECT" \
  -f compose/verification/docker-compose.issue280-operations.yml \
  -f compose/verification/docker-compose.issue312-sec-ingestion.yml config --quiet
docker compose --env-file "$APP_ENV_FILE" -p "$APP_COMPOSE_PROJECT" \
  -f docker-compose.yml -f docker-compose.override.yml port backend 8000
docker compose --env-file "$FUNDAMENTAL_ENV_FILE" -p "$FUNDAMENTAL_COMPOSE_PROJECT" \
  -f compose/verification/docker-compose.issue280-operations.yml \
  -f compose/verification/docker-compose.issue312-sec-ingestion.yml port fundamental-service 8080
```

Use `scripts/acceptance_preflight.sh` with the recorded tuple. It checks the worktree, branch, tested implementation commit, clean status when required, env-file SHA-256, required Compose variables, shell overrides, required SEC asset paths, Compose configuration, running services, published ports, application `/health`, and Fundamental `/readyz`. For SEC-backed acceptance set `REQUIRE_SEC_IDENTITY_RESOLUTION=1`; the preflight then requires the SEC ingestion overlay, a non-placeholder SEC contact, and the `identity_resolution_configured` readiness capability. A healthy container alone is not feature acceptance.

Store the tuple in `docs/acceptance/issue-<issue>-runtime.json` and run the preflight from that manifest:

```sh
ACCEPTANCE_MANIFEST=docs/acceptance/issue-355-runtime.json \
  scripts/acceptance_preflight.sh
```

When the isolated stack is not already running, use the same gate to start it
from the recorded tuple and then verify it:

```sh
ACCEPTANCE_MANIFEST=docs/acceptance/issue-355-runtime.json \
START_ACCEPTANCE_STACK=1 ACCEPTANCE_BUILD=1 \
  scripts/acceptance_preflight.sh
```

This command is the preferred entrypoint for a resumed acceptance run. It
validates Git and Compose configuration before starting anything, uses the
recorded projects, files, env paths, and ports, then checks service health and
feature readiness against those same values.

The manifest validator rejects missing fields, stale URL/port pairs, changed
env-file digests, sensitive values, missing SEC overlays, and a `VERIFIED`
status without passing checks. The required `contract-policy` workflow runs the
same policy on issue branches; a WIP or `BLOCKED` PR must remain draft. A
`VERIFIED` manifest records the exact implementation commit that was tested;
the PR head must descend from that commit and any later commits must change
acceptance metadata only. A PR cannot use a closing keyword until that policy
passes.

For Fundamental service work with no application workflow, use acceptance
schema version 2 with `acceptance_scope: fundamental-service`. This scope omits
`runtime.app` and `runtime.browser_session`; it must not invent either value.
The existing schema version 1 and the #351–#355 app/browser contracts remain
required for those issues. #361 is gated by the service scope in the same
required `contract-policy` job.

The service tuple records ordered `env_files` with a SHA-256 for each file, the
Fundamental image ID, installed package source digest and file count, Python/
Arelle/Pydantic versions, required healthy services and ports, and project-owned
networks and volumes. The same preflight entrypoint checks Git cleanliness and
ancestry, each env digest, shell overrides, Compose configuration hashes against
running containers, health, recorded host bindings, resource ownership, installed
source equality to Git, runtime versions and `/readyz`. It starts only recorded
services when `START_ACCEPTANCE_STACK=1`. Source or runtime drift fails before
acceptance. A passing preflight establishes the runtime tuple; it does not
establish replay acceptance or independent accounting review.

Service preflight also composes the SEC runtime in a fresh container process to
revalidate the mounted taxonomy, EDGAR, XULE, DQC and configured catalog pins.
An already started service can remain healthy after its mounted files disappear.
Keep certified resources in durable deployment storage, outside temporary cleanup
directories, and revalidate their original hashes when restoring them.

```sh
ACCEPTANCE_MANIFEST=docs/acceptance/issue-361-runtime.json \
  scripts/acceptance_preflight.sh --report-directory /tmp/issue361-preflight
```

Service preflight reports use canonical JSON and content-addressed names. A
repeat with the same tuple reuses existing bytes with `wrote=false`. Report
writes use a temporary file and atomic rename. The revised #361 tuple declares
`acceptance_profile: persistent-valuation-flow-v1`. A VERIFIED tuple requires
passing source acquisition/reuse, snapshot persistence, mapping, preparation,
forecast, calculation, artifact retrieval, restart/restore, deterministic repeat,
failure retention, concurrent deduplication, architecture, lint, type, diff,
service acceptance, full flow repeat and review checks, each bound to the exact
implementation commit and input/output digests. Historical threshold research
does not satisfy those checks; its evidence remains separate and unsupported
history thresholds remain null.
Later #361 evidence commits may change only that issue's acceptance Markdown
and JSON artifacts. Implementation changes require a new tested commit.

Exact-commit mode rejects tracked changes and every untracked path by default. If a runtime-only override is required, list its exact relative path in `ALLOWED_UNTRACKED_PATHS` and record that path in the tuple. The override remains runtime input and is never evidence that the commit contains the configuration.

Treat a changed Compose project, port, env-file, overlay, or browser session as a new runtime tuple. Open a fresh browser tab after that change and update the recorded URL; never reload a tab that still points at the old port.

## Protect `main` and keep CI usable

Configure a GitHub ruleset for `main` that requires pull requests and the repository's passing contract checks. Block force pushes and deletion. Apply the rules to administrators where the repository plan supports it. Protect the default branch before relying on this document as a merge gate.

Enable automatic deletion of merged head branches. Do not require a human approval count that the active maintainers cannot satisfy. Use CODEOWNERS only for paths with an available, accountable reviewer.

Use a merge queue only when the repository owner and GitHub plan support it, concurrent merges justify it, and every required CI workflow handles the `merge_group` event. A queue without merge-group checks cannot report the required statuses.

Keep required status-check names unique across workflows. Keep required PR checks fast enough for the project's change size. Run deployment or expensive release gates separately unless their results are required for every change.

Review open pull requests, integration branches, and stale branches during backlog cleanup. Flag branches that exceed five working days, pull requests with no recent progress, and issues whose acceptance criteria changed. Close abandoned work with a reason and preserve its recoverable changes before deleting resources.

## Retire branches, worktrees, and Compose resources

After merge, verify the pull request target, merge commit, clean worktree status, and issue state. Remove the worktree before deleting its local branch. Confirm that GitHub deleted the remote branch or delete it after verifying the merge. Run `git worktree prune` only to remove metadata for paths that no longer exist.

For cancelled or abandoned work, do not delete a dirty worktree until you identify its owner and preserve needed changes as a commit, patch, or bundle. Check `git worktree list --porcelain` and the worktree status first. Do not force-remove a worktree to bypass uncommitted changes or a lock.

Stop only the matching Compose project with `docker compose -p <project> down`. Inspect its project labels, named volumes, bind mounts, and contents before removing data. Keep named volumes unless their data is disposable or a verified backup exists. Never run a global Docker prune command for issue cleanup.

After merging a change that causes a regression, open a revert pull request to restore the last known good behavior. Do not rewrite shared `main` history. Reopen the issue if its acceptance criteria no longer hold. Record the regression, affected commit, recovery action, and follow-up issue. For data migrations, follow the documented recovery plan rather than assuming a code revert restores data.

## Name branches and worktrees

| Resource | Name |
| --- | --- |
| Direct issue branch | `codex/issue-<id>-<short-name>` |
| Parent integration branch | `codex/issue-<parent>-integration` |
| Parent integration worktree | `../value-investment-agent-issue-<parent>-integration` |
| Child worktree | `../value-investment-agent-issue-<child>-<short-name>` |
| Compose project | `value-investment-agent-<issue-or-parent>-<worktree>` |

Use [Docker development](../.agents/skills/docker-development/SKILL.md) when you start, test, or retire a Compose project. Keep task checklists in GitHub issues or Codex. Do not add a project-local task tracker.

## Record issue state and evidence

Use `integrated` to show that a child change passed on a parent integration branch. Use `VERIFIED` only after the full acceptance criteria pass against the commit being delivered to `main`. Close the issue only when its defined outcome is complete on `main`; use a separate rollout issue when release or deployment remains.

The parent issue records its child links, integration branch and worktree, final pull request, merge commit, verification evidence, and cleanup. Each child issue records its pull request, integration commit, acceptance evidence, and cleanup. Keep credentials, provider keys, session cookies, and personal data out of issues and pull requests.

## References

- [GitHub Flow](https://docs.github.com/en/get-started/using-github/github-flow) describes short-lived branches, pull requests, review, and branch cleanup.
- [GitHub sub-issues](https://docs.github.com/en/issues/tracking-your-work-with-issues/using-issues/adding-sub-issues) provide parent and child issue links.
- [Linking a pull request to an issue](https://docs.github.com/en/issues/tracking-your-work-with-issues/using-issues/linking-a-pull-request-to-an-issue) documents closing keywords and default-branch behavior.
- [Protected branches](https://docs.github.com/en/repositories/configuring-branches-and-merges-in-your-repository/managing-protected-branches/about-protected-branches) documents required reviews, status checks, and push restrictions.
- [Managing a merge queue](https://docs.github.com/en/repositories/configuring-branches-and-merges-in-your-repository/configuring-pull-request-merges/managing-a-merge-queue) documents plan eligibility and `merge_group` checks.
- [Automatic branch deletion](https://docs.github.com/en/repositories/configuring-branches-and-merges-in-your-repository/configuring-pull-request-merges/managing-the-automatic-deletion-of-branches) describes merged-branch cleanup.
- [DORA trunk-based development](https://dora.dev/capabilities/trunk-based-development/) recommends small batches, frequent merges, and short-lived branches.
- [Git worktree](https://git-scm.com/docs/git-worktree) documents linked worktree creation, removal, locking, and pruning.
