# IAM: roles, policies, and the resource hierarchy

> Source: https://cloud.google.com/iam/docs/overview
> Portions of this page are modifications based on work created and shared by Google and
> used according to terms described in the Creative Commons 4.0 Attribution License.

## Principals

A principal is an authenticated identity. Principals fall into two groups: human
identities (Google Accounts, groups, and federated identities) and workload identities
(service accounts and workload identity pools).

## The three role types

- **Predefined roles** are managed by Google Cloud services. These roles contain the
  permissions needed to perform common tasks for each given service.
- **Custom roles** are roles that you create that contain only the permissions that you
  specify. You have complete control over the permissions in these roles.
- **Basic roles** — Owner, Editor, Viewer — are highly permissive roles that provide
  broad access to Google Cloud services.
  These roles can be useful for testing purposes, but shouldn't be used in production environments.

Start from a predefined role that matches the task, and move to a custom role only when
no predefined role is narrow enough.

## Allow policies

An allow policy is a YAML or JSON object containing role bindings, each of which
associates a role with one or more principals. When an authenticated principal attempts
to access a resource, IAM checks the resource's allow policy to determine whether the
principal has the required permissions.

## The resource hierarchy and inheritance

Resources are organized as organization → folders → projects → service resources. Policy
flows downward: if you set an allow policy on a container resource, then the allow
policy also applies to all resources in that container.

Inheritance is additive and cannot be subtracted by a lower-level allow policy. A role
granted at the folder level cannot be removed by editing a project's policy — you have
to change the grant where it was made, or use a deny policy.
