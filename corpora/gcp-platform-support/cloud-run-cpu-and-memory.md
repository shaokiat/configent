# Cloud Run: CPU and memory limits

> Source: https://cloud.google.com/run/docs/configuring/services/cpu
> Portions of this page are modifications based on work created and shared by Google and
> used according to terms described in the Creative Commons 4.0 Attribution License.

## Default and allowed CPU values

By default, each instance is limited to 1 vCPU. Services can be configured with 1, 2, 4,
6, or 8 CPUs, up to a maximum of 8 vCPU. Fractional allocations are supported down to a
minimum of 0.08 vCPU.

## CPU-to-memory constraints

CPU and memory limits are not independent. A minimum of 0.5 vCPU is needed to set a
memory limit greater than 512MiB. A minimum of 1 vCPU is needed to set a memory limit
greater than 1GiB.

Raising memory alone on a service that is still at a fractional CPU will therefore be
rejected at deploy time rather than at runtime.

## Constraints on sub-1-vCPU services

Services configured with less than 1 vCPU carry three additional restrictions:

- Maximum concurrency must be set to 1.
- Billing settings must be set to request-based billing.
- The service must use the first generation execution environment.

## CPU count and application threading

Allocating more CPU does not always increase throughput. If your application is
single-threaded, it may only fully utilize one vCPU, so adding CPUs raises cost without
improving latency and can make metrics-based autoscaling less effective. Increase
concurrency or instance count instead.
