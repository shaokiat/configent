# Cloud Run: instance autoscaling

> Source: https://cloud.google.com/run/docs/about-instance-autoscaling
> Portions of this page are modifications based on work created and shared by Google and
> used according to terms described in the Creative Commons 4.0 Attribution License.

## How scaling decisions are made

By default, each Cloud Run revision is automatically scaled to the number of instances
needed to handle incoming requests. When a revision does not receive any traffic, by
default, it is scaled to zero instances.

Cloud Run evaluates two things when deciding how many instances to run: CPU and
concurrency utilization, and the instance limits you configure. It adjusts the instance
count to keep average CPU and concurrency within target thresholds.
By default, metrics-based scaling sets a 60% threshold for CPU utilization and request concurrency targets.

## Minimum instances

You can specify a number of idle instances to keep active so that requests do not wait
for a cold start. If your service is using CPU even when it's not processing requests,
you should set minimum instances to 1.

Setting minimum instances above zero means you are billed for those instances even when
they are idle, because they are held ready rather than scaled to zero.

## Maximum instances and request queuing

When a service is at its maximum instance count and all instances are busy, additional
requests are queued rather than rejected immediately. Requests will pend for up to 3.5
times average startup time of container instances of this service, or 10 seconds,
whichever is greater. Requests still waiting after that window fail with a 503.

Cloud Run might, for a short period of time, create more instances than are specified in
the maximum instances setting. Treat maximum instances as a scaling target and a cost
ceiling, not as a hard admission-control limit.

## Idle instance retention

Cloud Run might keep instances idle for a period of time after they finish handling
requests (up to 15 minutes, or 10 minutes for GPUs). An idle instance that receives a
request serves it without a cold start.
