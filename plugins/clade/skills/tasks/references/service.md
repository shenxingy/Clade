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
`project_id`, workspace, credentials-file and a systemd unit path. It refuses
existing directories and retains failed setup for diagnosis, without deleting
or reinitializing it. The prepared service is **not running or enabled**.

On Linux with a working systemd user manager, use the emitted unit path:

```bash
systemctl --user link /absolute/local-disk/clade-tasks-personal/clade-tasks-myproject.service
systemctl --user enable --now clade-tasks-myproject.service
systemctl --user is-active clade-tasks-myproject.service
```

Check the user manager's logout/reboot behavior (`loginctl show-user "$USER"
-p Linger`); enabling a unit alone does not prove it survives logout. Enabling
lingering requires the host's policy/authority. On other platforms, use the
site's process supervisor with the explicit command in private `service.json`.
Automatic boot recovery is unverified until actually observed.

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

For a full offline backup, stop this exact service, confirm it is stopped,
copy/archive the entire private instance directory to a separate protected
backup location, then restart and run a real snapshot query. Keep directory
permissions private: the backup includes credentials and SQL privileges.
Never copy live Dolt files as an allegedly consistent backup. JSONL task export
alone does not preserve all tables/history/leases.

Test restoration into a separate private directory while the original is
stopped: restore data plus privileges, adjust only machine-specific paths and
port/client configuration, start the restored server, then verify project ID,
task IDs, owners and accepted dependencies. Keep the prior backup generation.
The live tests exercise process restart and a stopped-store copy/restore; they
do not simulate power loss or prove a particular host's boot configuration.

Pin all clients to the verified version. Upgrade with a backup and one named
server operator; migration/restore is a separate operation, never an automatic
side effect added to session pickup.
