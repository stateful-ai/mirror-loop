# Security Policy

Mirror Loop is a hobby / research project maintained in spare time. We take
security seriously, but please calibrate expectations accordingly: there is no
on-call rotation and no security team behind this repo.

## Reporting a security issue

If you think you've found a security problem, please **do not** open a public
GitHub issue. Instead, pick whichever of these you prefer:

- **Email:** `security@mirror-loop.dev` (preferred for anything sensitive).
- **GitHub:** open a private security advisory — *Security → Advisories → New
  draft security advisory* on the repo.

Either is fine. A short description of what you found and how to reproduce it
is enough to get us started; a proof-of-concept is welcome but not required.

For ordinary, non-security bugs, a regular GitHub issue is the right channel.

## Supported versions

Only the current `main` branch is supported. Older tags are kept for history
and reproducibility but will not receive security fixes.

| Version        | Supported          |
| -------------- | ------------------ |
| `main` (HEAD)  | :white_check_mark: |
| everything else| :x:                |

## Response time

Best effort, hobby-project pace. As a rough guide:

- **Acknowledge:** within about a week.
- **Fix or workaround:** as quickly as the severity warrants, but measured in
  days-to-weeks, not hours.

If you don't hear back within two weeks, please nudge us — it almost certainly
means the report got lost, not that it was ignored.

## No bounties

We will **not** pay bug bounties or other monetary rewards. We're happy to
credit you in the release notes or advisory if you'd like; just say so in your
report.

Thanks for taking the time to make Mirror Loop a little safer.
