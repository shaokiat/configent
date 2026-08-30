# GKE: cluster autoscaler

> Source: https://cloud.google.com/kubernetes-engine/docs/concepts/cluster-autoscaler
> Portions of this page are modifications based on work created and shared by Google and
> used according to terms described in the Creative Commons 4.0 Attribution License.

## Scale up

If Pods fail to be scheduled on any of the current nodes, the cluster autoscaler adds
nodes, up to the maximum size of the node pool. Scale-up is driven by unschedulable
Pods, not by node CPU usage: a node pool sitting at 90% CPU with every Pod scheduled
will not grow.

## Scale down

The autoscaler removes underutilized nodes when all Pods could be scheduled even with
fewer nodes in the node pool. Nodes being removed get a graceful termination period of
one hour for GKE versions 1.32.7-gke.1079000 or later, and 10 minutes for earlier GKE
versions.

## What blocks a node from being removed

A node will not be removed if any Pod on it meets one of these conditions:

- The Pod's affinity or anti-affinity rules prevent rescheduling.
- The Pod is not managed by a Controller such as a Deployment, StatefulSet, Job or
  ReplicaSet.
- The Pod has the `cluster-autoscaler.kubernetes.io/safe-to-evict: false` annotation.
- The node's deletion would exceed the configured PodDisruptionBudget.

A single bare Pod — one created directly rather than by a controller — is enough to pin
a node indefinitely. This is the most common reason a cluster does not shrink after a
workload is removed.

## Node pool sizing

You specify a minimum and maximum size for the node pool, and the cluster autoscaler
makes rescaling decisions within these scaling constraints.
On Standard clusters, the cluster autoscaler never automatically scales down a cluster to zero nodes.
