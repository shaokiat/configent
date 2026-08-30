# Cloud Run: deployment and runtime errors

> Source: https://cloud.google.com/run/docs/troubleshooting
> Portions of this page are modifications based on work created and shared by Google and
> used according to terms described in the Creative Commons 4.0 Attribution License.

## Container failed to start

Error:
"Container failed to start. Failed to start and then listen on the port defined by the PORT environment variable."

Causes and fixes:

- The container is not listening on the port given in the `PORT` environment variable.
  Read the port from `PORT`; do not hardcode it.
- The container listens on `127.0.0.1` instead of all interfaces. Listen on `0.0.0.0`.
- The image is not compiled for 64-bit Linux, as required by the container runtime
  contract. On ARM-based machines such as Apple Silicon, build your image using Cloud
  Build rather than locally.

## Container startup timeout

Error: "Revision REVISION_NAME is not ready and cannot serve traffic. The user provided
container failed to start and listen on port defined by PORT=8080 environment variable
within the allocated timeout."

Common causes are a missing web server dependency, a container that cannot reach a
secret it needs at boot, or an application that simply takes longer to start than the
configured timeout. Specify the web server explicitly in your dependencies (for example
gunicorn, fastapi, or uvicorn), and confirm the service account has the Secret Manager
Secret Accessor role for any secret mounted at startup.

## Permission denied on deploy

Error: "User EMAIL_ADDRESS does not have permission to access namespace NAMESPACE_NAME"

This usually means the deploying principal cannot act as the runtime service account.
Grant the deployer the `iam.serviceAccounts.actAs` permission on the service account, or
pass a different one with `--service-account`. For deployments from source, the Cloud
Build service account also needs the Cloud Run Builder role.

## 503 errors at runtime

Three distinct causes produce a 503:

1. Memory exceeded: "While handling this request, the container instance was found to be
   using too much memory and was terminated." Raise the memory limit or fix the leak.
2. No available instance: "The request was aborted because there was no available
   instance." The service may have reached its maximum instance limit. Raise maximum
   instances or lower concurrency.
3. Malformed response: "The request failed because either the HTTP response was
   malformed or connection to the instance had an error." Check for liveness probe
   failures and framework timeout settings shorter than the request duration.
