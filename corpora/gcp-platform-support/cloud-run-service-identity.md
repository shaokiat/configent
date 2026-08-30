# Cloud Run: service identity

> Source: https://cloud.google.com/run/docs/securing/service-identity
> Portions of this page are modifications based on work created and shared by Google and
> used according to terms described in the Creative Commons 4.0 Attribution License.

## The default service account

By default, the Compute Engine default service account is automatically created. If you
don't specify a service account when the Cloud Run resource is created, Cloud Run uses
this service account. It takes the form
`PROJECT_NUMBER-compute@developer.gserviceaccount.com`.

Depending on your organization policy configuration, the default service account might
automatically be granted the Editor role on your project. That is far more access than a
typical service needs. You can prevent this by enforcing the
`iam.automaticIamGrantsForDefaultServiceAccounts` organization policy constraint.

## Per-service identities

The recommended alternative is a user-managed service account, of the form
`SERVICE_ACCOUNT_NAME@PROJECT_ID.iam.gserviceaccount.com`. You manually create this
service account and determine the most minimal set of permissions that the service
account needs to access specific Google Cloud resources.

Attach one at deploy time with the `--service-account` flag. Give each service its own
identity rather than sharing one across services, so that a compromise or a
misconfiguration is contained to a single workload and the audit log attributes actions
to a specific service.
