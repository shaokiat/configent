# IAM: troubleshooting access

> Source: https://cloud.google.com/policy-intelligence/docs/troubleshoot-access
> Portions of this page are modifications based on work created and shared by Google and
> used according to terms described in the Creative Commons 4.0 Attribution License.

## What the Policy Troubleshooter does

Policy Troubleshooter examines the allow policies, deny policies, and principal access
boundary (PAB) policies that impact the principal's access, and tells you whether, based
on those policies, the principal can use the specified permission to access the
resource.

## What it needs

Three inputs: the principal, resource, and permission you want to check.

- **Principal** — the email address to check.
- **Resource** — the full name of the resource that you want to troubleshoot access to.
- **Permission** — the permission to check, for example `run.services.get`.

## What it reports

The troubleshooter explains the overall verdict and how each policy type contributed.
For a user to be able to use the permission to access the resource, all policy types
must permit access — an allow policy granting a role is not sufficient if a deny policy
or a principal access boundary policy blocks it.

For each relevant role binding it reports whether the binding includes the permission,
whether it includes the principal, and whether conditions in the role binding, if any,
are met. A conditional binding whose condition evaluates false is the most common reason
a grant appears correct but produces a permission error.

It also accounts for inheritance: when you attach an allow or deny policy to a project,
folder, or organization, that policy also applies for all resources inside that project,
folder, or organization.
