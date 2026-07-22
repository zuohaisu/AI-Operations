# Autonomy

## Act without asking
Read files · search code · analyze structure · create NEW files · run tests/lint/build
· web search · fetch docs · generate reports and documents · git commit (clean tree only)
· edit a file with no uncommitted changes

## Ask first — always
- Delete anything (file, directory, branch, record). List what would be deleted, then wait.
- Edit a file that has uncommitted changes in it. Check `git status` first.
- Install a package not already in the lockfile.
- Destructive git: force push, hard reset, rebase on shared branches, branch delete.
- Modify production config, environment variables, or CI configuration.
- Push code, open or merge a PR.
- Database migration or schema change.
- Anything touching keys, tokens, credentials, or PII.
- Any irreversible infrastructure change.

## Default
When uncertain which column applies: inspect, report, wait. Inspection is free;
a wrong write is not.
