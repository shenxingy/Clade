# Personal task service

Use Beads **1.3.1** and Dolt **2.2.0** for this adapter. Download the official
release binaries and verify the published checksums/digests before use. Neither
Clade's installer nor opening a session installs these tools or starts a service.

- [Beads release](https://github.com/gastownhall/beads/releases/tag/v1.3.1)
- [Dolt release](https://github.com/dolthub/dolt/releases/tag/v2.2.0)
- [Beads server architecture](https://github.com/gastownhall/beads/blob/v1.3.1/docs/architecture/dolt.md)

This version uses an explicit external Dolt server. Beads' proxied-server
default in this release cannot execute strict read-only queries, which the
monitoring path requires. Do not remove `--readonly` to work around that gap.

## Prepare a new personal instance

Choose a stable host and an unused port. Verify the parent directory is on
host-local storage (`findmnt -T /chosen/parent` on Linux); keep active database
files off NFS/shared network mounts. Use an absolute directory outside any code
checkout. It must not already exist. No GPU or model process is required.

From the installed tasks skill directory:

```bash
python3 scripts/service.py --directory /absolute/local-disk/clade-tasks-personal \
  --prefix myproject --port 13307 --bd /absolute/bin/bd --dolt /absolute/bin/dolt
```

The helper creates private data/workspace directories, creates a passworded
SQL account before opening the listener, initializes one project, checks that
anonymous root access fails, and stops the temporary setup server. It emits
`project_id`, workspace, credentials-file, systemd units and an install command. It refuses
existing directories and retains failed setup for diagnosis, without deleting
or reinitializing it. The prepared service is **not running or enabled**.

On Linux with a working systemd user manager, run the emitted install command:

```bash
python3 /absolute/local-disk/clade-tasks-personal/runtime/maintenance.py \
  --directory /absolute/local-disk/clade-tasks-personal install
```

Check the user manager's logout/reboot behavior (`loginctl show-user "$USER"
-p Linger`); enabling a unit alone does not prove it survives logout. Enabling
lingering requires the host's policy/authority. On other platforms, use the
site's process supervisor with the explicit command in private `service.json`.
Automatic boot recovery is unverified until actually observed. The automatic
maintenance installer is Linux/systemd-only; other supervisors need their own
health, backup and recovery integration, not a claim that these timers run there.

Bind the code repository using the values emitted by setup:

```bash
python3 scripts/tasks.py --repo /absolute/code/repo bind \
  --workspace /absolute/local-disk/clade-tasks-personal/workspace \
  --project-id PROJECT_ID --bd /absolute/bin/bd \
  --credentials-file /absolute/local-disk/clade-tasks-personal/credentials.ini
python3 scripts/tasks.py --repo /absolute/code/repo snapshot
```

The last command performs a real authenticated read. A listening port or
`is-active` alone is not a readiness check. Bindings/sessions live in Git-common
`clade/tasks/`, never in committed project files. Native Codex, CC and Kimi all
use the same helper; installation does not change their existing agent hooks.

## Sharing and additional projects

One service can host several databases. The bootstrap helper deliberately
prepares one personal instance/project first. An operator may add databases and
client workspaces using Beads' explicit server configuration. Give each project
its own prefix/database and expected project ID. Every client of a project
connects to the same live server database; Git/Dolt replicas are backups or
exchange, not a distributed atomic claim mechanism.

Separate clones bind separately; local worktrees inherit their common binding.
On another machine, provision a private Beads client workspace pointing to the
same server (using a protected tunnel or authenticated TLS), then verify its
project ID before binding. The adapter strips ambient routing variables; put
server routing in that workspace's explicit Beads configuration. Passwords may
come from the bound private credentials file or the supported Beads password
environment, never command arguments or repository files.

The prepared listener is loopback-only but still requires authentication:
other local Unix users must not gain access just by guessing a port. The single
SQL account has authority over this personal instance. Use separate instances
and credentials for personal and trusted-team spaces until project-scoped
authorization is implemented and tested. Task assignees/session IDs are not ACLs.
Do not publish the raw database or Beads HTTP endpoint to the public internet.

## Restart, backup and upgrade

The service owns persistence and backup. A client must not start a substitute
database when the server is unavailable. Existing code can be checkpointed;
new claims wait for the real backend to return.

Installation includes an actual initial backup and isolated restore check. A
failed check fails installation; enabled timers alone are not success. Stable
copies of the three helpers live under the private instance's `runtime/`, so
timers do not depend on a temporary worktree or a plugin cache version.

- Authenticated, strict read-only health checks run every five minutes. They
  verify project identity, the actual client endpoint, SQL file restrictions,
  enabled/active service and timers, and backup freshness. Observations older
  than 15 minutes are degraded even if the last result was healthy.
- A daily backup runs at 03:30 in the host's timezone, with up to ten minutes
  of jitter. The persistent timer catches missed runs. It stops the exact
  database unit, confirms it is inactive, copies data/workspace/credentials,
  then restarts it before compression and restore verification. Claims are
  briefly unavailable during the copy; do not create another database.
- Every backup is extracted into a fresh temporary directory, verified against
  file hashes, and started read-only on a separate loopback port. The copied
  Beads port file, YAML, metadata and credentials are all redirected. Project
  identity, task reads and full issue/dependency/event tables must be readable.
  Only then is the archive published and counted toward the seven retained
  verified generations. Failed attempts preserve the previous good backups.
- A per-instance lock prevents overlapping maintenance. A restart receipt and
  systemd `ExecStopPost` recovery resume the database after a failed or killed
  backup helper. Recovery never initializes a new database or replaces data.
- Service and timer logs go to journald using the host's retention policy.
  Private `maintenance/events.jsonl` rotates at 1 MiB with three older files.
  `status.json`, `alert.json` and `backup.json` preserve the latest observations;
  failure/recovery alerts are deduplicated on state changes. `/status` and
  `/pipeline` consume them locally, including stale timer observations. No
  Telegram, email or webhook is enabled by this installer.

The installer registers this instance in `~/.clade/task-services/`. The existing
pipeline checker reads that registry alongside its YAML project registry. A
broken database can therefore still have a readable maintenance status:

```bash
python3 scripts/maintenance.py --repo /absolute/code/repo status
journalctl --user -u clade-tasks-myproject.service -u clade-tasks-myproject-health.service
systemctl --user list-timers 'clade-tasks-myproject-*'
```

To trigger a backup now, start `clade-tasks-myproject-backup.service` through
systemd (this preserves its crash-recovery hook). To repeat a restore drill:

```bash
python3 scripts/maintenance.py --directory /absolute/local-disk/clade-tasks-personal \
  verify --archive /absolute/local-disk/clade-tasks-personal/backups/BACKUP_DIRECTORY
```

This verifies into a separate directory and never overwrites production. Keep
backups private: they contain passwords and SQL privileges. These are local
recovery copies on the same host, not protection against host/disk loss. An
off-host destination and external alert recipient require explicit operator
configuration. The tests do not simulate power loss or reboot the host.

For an existing prepared instance, run the **newly installed skill's**
`scripts/maintenance.py --directory /absolute/instance install`. It upgrades
the unit/configuration and stable helpers, restarts the service, enables both
timers, and performs the same initial backup/restore verification. It refuses
a unit or project registration belonging to another instance. It does not
reinitialize the project; existing bindings and session IDs remain valid.

Pin all clients to the verified version. Upgrade with a backup and one named
server operator; migration/restore is a separate operation, never an automatic
side effect added to session pickup.
