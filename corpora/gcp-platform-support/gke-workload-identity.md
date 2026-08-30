# GKE: Workload Identity Federation

> Source: https://cloud.google.com/kubernetes-engine/docs/concepts/workload-identity
> Portions of this page are modifications based on work created and shared by Google and
> used according to terms described in the Creative Commons 4.0 Attribution License.

## The problem it solves

Applications running on GKE might need access to Google Cloud APIs such as the Compute
Engine API, BigQuery Storage API, or Machine Learning APIs. Workload Identity Federation
for GKE lets a Pod authenticate to those APIs as an IAM principal without a credential
file mounted into the container.

## Why not service account keys

Service account keys are a security risk if not managed correctly. Choose a more secure
alternative to service account keys whenever possible. If you must authenticate with a
service account key, you are responsible for the security of the private key — its
storage, its rotation, and its revocation if it leaks.

## How Kubernetes identities map to IAM

Kubernetes workloads are referenced directly as IAM principals. You can select workloads
by name or by UID, which allows fine-grained grants: for example, you could give read
permissions on a Cloud Storage bucket to all Pods that use the `database-reader`
Kubernetes ServiceAccount.

The principal identifier takes this form:

```
PREFIX://iam.googleapis.com/projects/PROJECT_NUMBER/locations/global/workloadIdentityPools/PROJECT_ID.svc.id.goog/SELECTOR
```

`PREFIX` is `principal` for a single resource or `principalSet` for a set of them, and
`SELECTOR` identifies the target Kubernetes resource. Note the pool name is derived from
the project ID (`PROJECT_ID.svc.id.goog`) while the path uses the project *number* —
mixing the two is a frequent cause of bindings that appear correct but never match.
