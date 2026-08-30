# IAM: service account best practices

> Source: https://cloud.google.com/iam/docs/best-practices-service-accounts
> Portions of this page are modifications based on work created and shared by Google and
> used according to terms described in the Creative Commons 4.0 Attribution License.

## Avoid service account keys

We recommend that you avoid using service account keys whenever possible. Prefer
Workload Identity Federation or service account impersonation, both of which issue
short-lived credentials rather than a long-lived secret you have to store.

Authenticating with a service account key introduces a non-repudiation threat: the key
identifies the service account, not the person who used it, so the audit log cannot tell
you who actually performed an action. Impersonation logs the originating user.

## One service account per workload

Create dedicated service accounts for each application, and avoid using default service
accounts. Default service accounts often hold the Editor role, and it's very risky to
share such a powerful service account across multiple applications: every workload
inherits the union of every other workload's access, and an audit trail cannot separate
them.

## Limit who can create keys

Don't let a user create service account keys for service accounts that have more
privileges than they do — otherwise key creation becomes a privilege-escalation path. If
your deployment does not require keys at all, disable their creation entirely with the
`constraints/iam.disableServiceAccountKeyCreation` organization policy constraint.
