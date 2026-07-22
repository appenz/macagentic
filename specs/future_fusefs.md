# FUSE Agent Filesystems

IMPORTANT: This Spec describes a proposed design. It is NOT implemented in the code. It should be ignored for all planning and implementation tasks as it will likely change.

## Overview

Each agent works in one macFUSE volume mounted at
`/Volumes/agent-<id>`. The volume combines private scratch storage, a shared
skills snapshot, and the user directories configured in `[mounts]`.

For example, with a configured `notes/private` directory, agent 7 sees:

```text
/Volumes/agent-7/
├── skills/                 shared skills snapshot, read-only
│   └── summarize/
│       └── SKILL.md
├── notes/
│   ├── private/            configured user directory, read-write
│   └── draft.txt           private scratch storage
└── result.txt              private scratch storage
```

This is one FUSE filesystem, not a collection of nested mounts. FUSE maps
`skills/` to the shared skills snapshot, `notes/private/` to its configured
source, and all other paths to agent 7's scratch directory under
`~/.tmpagent/7`.

The agent root therefore contains ordinary directories rather than
references to directories elsewhere. The number of configured directories
does not change the number of volumes or FUSE processes.

## Architecture

`AgentWorkspace` owns the complete filesystem lifecycle for one agent:

```python
class AgentWorkspace:
    id: int
    mount_path: Path
    storage_path: Path
    grafts: tuple[Graft, ...]
    fuse_process: subprocess.Popen
```

- `id` is the process-local agent ID.
- `mount_path` is the mounted `/Volumes/agent-<id>` directory.
- `storage_path` is the private `~/.tmpagent/<id>` directory.
- `grafts` is the immutable mapping from virtual paths to source directories
and access modes.
- `fuse_process` is the dedicated Python process serving the volume through
`mfusepy` and macFUSE's libfuse2-compatible API.

`MacAgenticApp` creates an `AgentWorkspace` before constructing an `Agent`.
`Agent` retains the workspace and exposes `workspace.mount_path` as
`Agent.root`. The shell runner uses that path as its current working directory
and as `$AGENT_ROOT`. The agentic loop does not otherwise interact with FUSE.

The FUSE process receives the storage path and immutable graft table when it
starts. Each filesystem operation is routed to exactly one backing directory.
Opened files continue to use their backing file descriptor.

macAgentic creates one shared, read-only skills snapshot before creating
workspaces. Every workspace includes that directory as its `/skills` graft.

## Platform

The filesystem targets macOS 26 or newer and macFUSE 5.0.7 or newer using
the FSKit backend. It does not support or enable the legacy kernel-extension
backend.

The filesystem server is written in Python using `mfusepy` and macFUSE's
libfuse2-compatible API. Mounting explicitly requests `backend=fskit`.

If the required OS, macFUSE installation, or FUSE library is unavailable,
workspace creation fails.

## Workspace Creation

An agent ID is also a workspace slot. macAgentic checks
`/Volumes/agent-<id>` and skips to the next ID when that path already exists.

For the first available slot, macAgentic wipes and recreates
`~/.tmpagent/<id>`, then asks macFUSE to create and mount
`/Volumes/agent-<id>`. The selected ID is used for both `AgentWorkspace` and
`Agent`. An `AgentWorkspace` is returned only after the volume is ready.

macAgentic never inspects, deletes, or unmounts an existing candidate path
under `/Volumes`. This permits multiple application and test processes to
allocate workspaces independently. Slots leaked by an unclean exit are simply
skipped. If no slot through ID 999 can be claimed, workspace creation fails.

## Virtual Namespace

The immutable graft table maps configured paths to their user directories;
all other paths use `storage_path`. Grafts may be nested, cannot overlap, and
cannot use the reserved `skills` name. Operations crossing a graft boundary
fail with `EXDEV`.

The existing `[mounts]` configuration remains unchanged.

## Skills Snapshot

Skills are copied once per application launch into one shared snapshot.
Top-level skill directories are physical directories, and complete skill
contents are copied so adjacent assets remain available. All agents see the
same read-only snapshot; source changes become visible after restarting
macAgentic.

## Lifecycle

Closing an `AgentWorkspace` first stops active tool processes, then unmounts
the volume and removes its FUSE process, mountpoint, and backing directory.
Close is idempotent and is called explicitly when an agent closes.

Unexpected parent-process termination also causes the FUSE process to exit
and the volume to unmount.

## Failure Model

Ordinary filesystem errors are returned to the tool that caused them. An
unexpected FUSE-process exit, inaccessible live volume, or failed unmount
makes the workspace unusable and is reported as a fatal infrastructure error.
There is no automatic remount or symlink fallback.