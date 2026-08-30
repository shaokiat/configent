# GKE: Autopilot and Standard modes

> Source: https://cloud.google.com/kubernetes-engine/docs/resources/autopilot-standard-feature-comparison
> Portions of this page are modifications based on work created and shared by Google and
> used according to terms described in the Creative Commons 4.0 Attribution License.

## Who manages the nodes

In Autopilot mode, GKE manages the nodes, including node configuration, autoscaling, and
security constraints. In Standard mode, you create and manage nodes in node pools.

## Scaling and provisioning

Autopilot automatically scales the quantity and size of nodes based on the Pods in the
cluster; there are no node pools to size. Standard clusters default to manually
provisioned nodes and manually specified node resources, with cluster autoscaling and
node auto-provisioning available as options you turn on.

## Security defaults

Autopilot clusters have Workload Identity Federation for GKE, Shielded GKE Nodes, and
GKE Sandbox enabled by default. Standard clusters enable Shielded GKE Nodes by default;
the others are optional and must be configured.

## Upgrades and repair

Autopilot provides node auto-repair and node auto-upgrade as pre-configured features.
Standard clusters have them on by default for clusters enrolled in a release channel.

## Topology

Autopilot clusters are regional. Standard clusters can be regional or zonal.

## Choosing between them

Autopilot removes node-level decisions and bills for the resources your Pods request.
Standard keeps node-level control — custom machine types, DaemonSets that need host
access, GPU node pools you shape yourself — and bills for the nodes you run whether or
not Pods fill them. Neither is universally the right default; the question is whether
you need node-level control enough to take on node-level operations.
