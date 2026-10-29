# Issue and worktree lifecycle

Use short-lived issue branches as the default. Create one parent integration branch and worktree only when a parent issue contains changes that must be tested and merged together. A permanent integration branch for every parent would add another long-lived branch, increase merge conflicts, and delay feedback. Keep `main` buildable and integrate small changes often.

An issue hierarchy does not require a branch hierarchy. A parent issue can group child issues whose pull requests each target `main`. Prefer that path when each child can land safely on its own. Use a parent integration branch when intermediate child changes would leave the product or a shared contract in an invalid state. Use feature flags, expand-and-contract migrations, or branch-by-abstraction when they let you land safe increments on `main`.

## Deliver one issue directly to `main`

1. Confirm that the issue has a clear outcome and acceptance criteria.
2. Fetch `origin` and create a short-lived issue branch and worktree from `origin/main`.
3. Keep the change within the issue. Link a new design or ownership gap to a separate issue labeled `blocker` before adding a workaround.
4. Run the relevant tests and checks. Inspect the complete diff against the issue criteria.
5. Open a pull request to `main`. Link the issue and use `Closes #<issue>` when the pull request satisfies its acceptance criteria.
6. Merge after review, required checks, and any real-application acceptance pass.
7. Confirm that `main` contains the change and GitHub closed the issue. Remove the merged branch and worktree.

Example:

```sh
git fetch origin
git worktree add -b codex/issue-<id>-<short-name> ../value-investment-agent-issue-<id> origin/main
```

## Coordinate a parent issue through an integration branch

Use this flow only when the parent acceptance criteria require the child changes to land together. Create one parent integration branch and keep one dedicated integration worktree checked out on that branch. Give each active child branch its own temporary worktree so work does not overwrite the integration checkout.

1. Create a parent issue with one bounded outcome, explicit final acceptance criteria, and linked GitHub sub-issues.
2. Create `codex/issue-<parent>-integration` from the latest `origin/main`. Create a dedicated worktree for that branch.
3. Record the branch, worktree path, Compose project name, child issues, acceptance commands, and expected cleanup in the parent issue.
4. Create each child branch from the latest integration branch commit. Give it a temporary worktree while the issue is active.
5. Keep each child change within its issue. Run the child checks and inspect the full diff before requesting integration.
6. Open a pull request from the child branch to the parent integration branch. Link the child issue and parent issue. Do not use `Closes #<child>` on this pull request.
7. Merge one child pull request at a time. After each merge, update the integration worktree and run the checks affected by the new code.
8. Close the child issue only after the integration branch contains the change and the child acceptance criteria pass. Apply an `integrated` label or project status so readers can distinguish this from work already merged to `main`. Record the pull request, merge commit, and verification in the child issue.
9. Delete the merged child branch and retire its temporary worktree. Stop its uniquely named Compose project. Keep its volumes unless their data is disposable or backed up.
10. Open a pull request from the integration branch to `main` as soon as it is useful for review. Keep it draft until parent acceptance passes. Refresh it from `origin/main` before final verification.
11. Merge the parent pull request only after all child issues are integrated and the parent acceptance criteria pass. Use `Closes #<parent>` in this pull request.
12. Confirm that the merge commit is on `main` and GitHub closed the parent issue. Delete the integration branch and retire its worktree and Compose project.

GitHub only interprets closing keywords for pull requests that target the default branch. It ignores those keywords for child pull requests targeting the integration branch. Link child issues to their pull requests manually through the issue or pull request Development panel. Close child issues explicitly after integration checks pass.

Closing a child issue at this stage means "integrated into the parent branch." It does not mean "merged to `main`" or "released." Keep the parent open until its pull request merges to `main`. If the acceptance criteria include deployment, keep the parent open until deployment is verified.

Keep the integration branch short-lived. Merge the latest `origin/main` into it before child merges and final acceptance. Merge completed child pull requests promptly instead of waiting for every child. If several child changes must wait together or the integration phase lasts days, split the work and land safe increments on `main` behind a feature flag or through a compatible migration.

Example:

```sh
git fetch origin
git worktree add -b codex/issue-<parent>-integration ../value-investment-agent-issue-<parent>-integration origin/main
git worktree add -b codex/issue-<child>-<short-name> ../value-investment-agent-issue-<child>-<short-name> codex/issue-<parent>-integration
```

## Keep parallel work safe

Start child branches from the current integration commit, not from an older child branch. Parallelize only when the changes do not conflict over files, APIs, schemas, migrations, or shared runtime data. Merge pull requests serially. Before merging each pull request, update its child branch from the latest integration branch and rerun affected checks. Rebase a private child branch. Merge the integration branch into a child branch when others depend on its published history.

Keep one Git branch checked out in one worktree at a time. Give every active worktree a unique Compose project name and published host ports. Do not start a full stack in every worktree unless the task needs it.

## Require these checks before merging

- The pull request diff matches its issue scope and acceptance criteria.
- Relevant tests, type checks, lint, contract checks, and security checks pass.
- Docker services required by the acceptance criteria are healthy.
- Browser acceptance exercises the real route and user action when the change affects a user workflow. Mocked tests alone do not prove end-to-end behavior.
- A schema or migration change has an explicit upgrade and rollback or recovery plan.
- A blocker is resolved in its owning layer. Do not mark blocked work verified or merge it around the blocker.

Protect `main` from direct pushes and force pushes. Require the repository's relevant automated checks before merge. Use a merge queue when multiple pull requests may land concurrently and the repository has that feature enabled. Delete merged remote branches automatically when the repository setting is available.

Review the age of open branches and pull requests during backlog cleanup. A growing count of stale branches or integration pull requests signals that issues are too broad, child changes are waiting too long, or branch cleanup is incomplete.

## Retire branches, worktrees, and Compose resources

After a pull request merges, verify the merge target and confirm that no uncommitted work remains in the worktree. Then remove the worktree and local branch. Confirm that the remote branch was deleted automatically or delete it after verifying the merge. Run `git worktree prune` only to remove stale Git metadata for paths that no longer exist.

If a merged change breaks `main`, use a revert pull request to restore the last known good behavior. Do not rewrite shared `main` history. Keep the issue open or reopen it if its acceptance criteria no longer hold. Record the regression and follow-up issue in the revert pull request.

Stop the matching Compose project with `docker compose -p <project> down`. Compose keeps named volumes by default. Before removing a volume, inspect its project label and contents. Delete it only when it contains disposable local data or a verified backup exists. Never use a global Docker prune command for issue cleanup.

Do not delete branches or worktrees for unmerged issues. For cancelled work, preserve any uncommitted changes that the owner needs before retiring the checkout. Never remove a user's active checkout or shared project data as a side effect of closing an issue.

## Name branches and worktrees

| Resource | Name |
| --- | --- |
| Direct issue branch | `codex/issue-<id>-<short-name>` |
| Parent integration branch | `codex/issue-<parent>-integration` |
| Parent integration worktree | `../value-investment-agent-issue-<parent>-integration` |
| Child worktree | `../value-investment-agent-issue-<child>-<short-name>` |
| Compose project | `via-<parent-or-issue>-<child-or-integration>` |

Use [Docker development](../.agents/skills/docker-development/SKILL.md) when you start, test, or retire a Compose project. Keep task checklists in GitHub issues or Codex. Do not add a separate project-local task tracker.

## Record decisions and evidence

The parent issue records its child issue links, integration branch and worktree, final pull request, merge commit, acceptance results, and cleanup. Each child issue records its pull request, integration merge commit, relevant test results, and cleanup. Keep credentials, provider keys, session cookies, and other secrets out of issues and pull requests.

## References

- [GitHub Flow](https://docs.github.com/en/get-started/using-github/github-flow) recommends descriptive branches, reviewable changes, pull requests, and deleting branches after merge.
- [GitHub sub-issues](https://docs.github.com/en/issues/tracking-your-work-with-issues/using-issues/adding-sub-issues) provide a built-in parent and child issue hierarchy.
- [Linking a pull request to an issue](https://docs.github.com/en/issues/tracking-your-work-with-issues/using-issues/linking-a-pull-request-to-an-issue) documents that closing keywords only work when the pull request targets the default branch.
- [Protected branches](https://docs.github.com/en/repositories/configuring-branches-and-merges-in-your-repository/managing-protected-branches/about-protected-branches) documents required reviews, checks, merge queues, and push restrictions.
- [Deleting and restoring branches in a pull request](https://docs.github.com/en/repositories/configuring-branches-and-merges-in-your-repository/managing-branches-in-your-repository/deleting-and-restoring-branches-in-a-pull-request) documents when GitHub allows branch deletion and restoration.
- [DORA trunk-based development](https://dora.dev/capabilities/trunk-based-development/) recommends small batches, frequent merges, and avoiding long integration phases.
- [Git worktree](https://git-scm.com/docs/git-worktree) documents linked worktree creation, removal, and stale metadata cleanup.
