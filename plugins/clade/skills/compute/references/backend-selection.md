# Select the smallest established backend that fits

Read only the relevant backend's installed help and official documentation.
These choices describe capabilities, not evidence of a healthy installation.
Prefer the site's existing allocation system; frameworks can run inside it.

| Workload / environment | Starting choice | Boundary to verify |
| --- | --- | --- |
| Shared multi-user GPU/CPU fleet with operational Slurm | Slurm jobs/arrays; framework inside allocation | Healthy eligible nodes, account/partition, resource enforcement, requeue policy |
| Independent commands on one/few authorized hosts | GNU Parallel inside bounded persistent systemd services | Cross-run admission budget, immutable joblog/input mapping, local staging, restart activation |
| Python task/actor pipeline or ML sweep already using Ray | Ray Core/Data/Train/Tune inside allocated resources | Explicit actor/task CPU/GPU requests, object-store/heap budget, backpressure, checkpoint contract |
| Partitioned tabular/array DAG already using Dask | Dask Distributed inside allocated resources | Local spill space, worker limits, partition size, transfer/serialization cost |
| Small bounded local task | Existing process pool or project runner | A cluster adds no value unless measurements justify it |

## Slurm

Use `scontrol ping`, `sinfo -N -l`, `squeue` and relevant partition/node details.
DOWN/DRAIN/unknown nodes are unavailable even with an empty queue. Inspect the
configured resource selection and cgroup enforcement before assuming `--mem`
or GPU requests isolate jobs. Work outside Slurm still consumes real capacity.
Do not resume DOWN nodes merely to make a submission run.

Inspect permitted account/partition/QOS associations and effective limits using
site-provided read-only views (`sacctmgr show` where permitted), allocation
details and pending reasons. Check user and account/group resource usage, running
and submitted job limits, wall time and resource-minute budgets. Slurm has its
own QOS/association precedence and exceptions; do not take the numeric minimum
of every configured field. Verify accounting enforcement; hidden records are
not evidence of no limit. Use the site's admission authority without changing
associations/QOS or choosing another account to evade a quota. A submission may
be rejected rather than queued when a limit is reached; retain its plan and
reason, with bounded retries only for conditions that can clear.

Use an array with a measured concurrency cap (`--array=0-N%K`) for independent
shards, explicit CPU/memory/time/GPU requirements, and a stable index-to-shard
manifest. Split resource classes into separate arrays. The order in a nodelist
is not a preference order: express host tiers through verified partitions,
constraints or submission policy. Avoid submitting the same shard to primary
and fallback queues simultaneously.

Requeue restarts the batch script from its beginning. The script must find and
validate application checkpoints, and transient failures need a bounded retry
policy. A signal handler helps graceful stops; periodic checkpoints are needed
for abrupt loss. Never assume `--requeue` preserves process memory.

Sources: [job arrays](https://slurm.schedmd.com/job_array.html),
[sbatch resource requests and requeue](https://slurm.schedmd.com/sbatch.html),
[resource-limit hierarchy and enforcement](https://slurm.schedmd.com/resource_limits.html).

## GNU Parallel and systemd

Use a fixed input manifest, bounded `--jobs`, persistent `--joblog` and
`--resume-failed` for retryable independent jobs. Resume depends on unchanged
input order and command; if either changes, derive a new manifest from validated
stable output IDs. The joblog is task history, not output validation or a
cross-user resource scheduler. `--memfree` is not a hard memory limit (under
pressure it may kill/retry a job); pair it with checkpoint-safe tasks and cgroups.
Bound remote transfers separately. Prefer host-local workers over repeatedly
shipping the same dataset via SSH for each item.

Use persistent `.service`/`.timer` definitions when reboot restart is required.
Set `MemoryHigh`/`MemoryMax`, `MemorySwapMax`, CPU budget and restart/backoff
according to the host policy; verify effective limits including ancestors.
Sibling services need an aggregate slice budget or one common admission owner,
not independent copies of the whole allowance. GPU allocations still require
the site's GPU admission system; systemd alone does not reserve VRAM.

Use restart only for retryable failures, with a finite attempt/deadline budget.
A timer can recheck admission without busy polling. Read back the installed
unit, enabled state, resource properties and user lingering; then interrupt a
task-owned smoke job and observe its actual resume. Never enable an infinite
restart loop on malformed input. Do not call a transient service reboot-safe.

Sources: [GNU Parallel manual](https://www.gnu.org/software/parallel/man.html),
[systemd resource control](https://www.freedesktop.org/software/systemd/man/latest/systemd.resource-control.html),
[service restart](https://www.freedesktop.org/software/systemd/man/latest/systemd.service.html),
[user lingering](https://www.freedesktop.org/software/systemd/man/latest/loginctl.html).
If online systemd docs are inaccessible, inspect the target's installed manual
and `systemctl show`; do not assume support for a flag from another version.

## Ray and Dask

Choose these for the application's task graph, not to replace site admission.
Account for driver, scheduler, object store, workers, prefetch and serialization
memory within the allocation. Bound submissions so the driver cannot enqueue
an unbounded graph. Keep framework dashboards/control ports within the site's
approved access boundary.

Ray's resource declarations are logical admission controls, not physical CPU
or RAM limits. Declare actor CPU requirements explicitly; bound threads and
use OS limits. GPU visibility is not a VRAM partition. Task/actor retries and
training checkpoint restore are separate contracts; verify each for the actual
framework version. Use data locality and coherent placement for training.

Dask worker memory handling can spill, pause and terminate/restart workers.
Choose host-local spill storage and leave memory for unmanaged/native-library
allocations. Lost worker data may require recomputation; this does not make
external writes idempotent or preserve a whole run after scheduler loss.

Sources: [Ray resources](https://docs.ray.io/en/latest/ray-core/scheduling/resources.html),
[Ray scheduling](https://docs.ray.io/en/latest/ray-core/scheduling/index.html),
[Dask worker memory](https://distributed.dask.org/en/stable/worker-memory.html).

## Profiling and assignment

Start with stage timing plus process-tree memory and host I/O/GPU samples.
Use the application's profiler only for the limiting stage. For training,
sample warmup and a bounded active interval with
[PyTorch Profiler](https://docs.pytorch.org/tutorials/recipes/recipes/profiler_recipe.html).
Include an unprofiled sustained sample; trace overhead distorts capacity.

Optimize useful items/second including staging, queue wait, checkpoint and sync,
not core occupancy. Increase workers/batch size until throughput plateaus or
pressure rises, then keep the best safe setting. Record the experiment rather
than assuming more workers or a distributed framework is faster. Limit the
number of tuning trials to fit the task budget.

Use per-shard cost estimates and dynamic dispatch, separate outliers, and
backpressure between stages. Prefer local cached data when transfer dominates;
compare tail time and idle slots before rebalancing. A larger queue can hide
variation but cannot fix a saturated shared disk. If GPU is idle waiting on
decode, improve measured CPU/input throughput instead of allocating more GPUs.
