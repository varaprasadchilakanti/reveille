# 0033 — Line counts are read in chunks, by up to eight Git processes

**Status:** Proposed (2026-11-18). Supersedes in part ADR 0019: its "one `git log` read for the
records".

## Context

ADR 0019 decided: "**One `git log` read for the records, one `git rev-list` for the commit set,
one `git log -z` for trailers**, and, only when an author is excluded, one more `git log` reading
names and addresses across all history (ADR 0020). Never one process per commit." This record
replaces "one `git log` read for the records"; the rest of that bullet stands. With
`--numstat` that read is most of a report's time: Git computes each commit's diff, in one process,
on one CPU. Measured with Git 2.56.1 on Linux, 20 CPUs, a repository of 4,376 non-merge commits:
`git log --numstat` took 5.0 s, and `generate --deterministic` 6.2 s.

Each commit's diff is computed independently of the others, so the read can be split.
`git log --no-walk=unsorted --stdin` logs the commits it is given, in the order given.

## Considered options

- **One `git log` (ADR 0019).** One process for any repository size.
- **Round-robin split of the commits.** Even load, but the records come back interleaved and must
  be put back in log order by the hash in each record's header. That header can be forged (ADR
  0019), so the order would depend on text a commit's author controls.
- **Contiguous chunks over a fixed pool (chosen).** Records come back in log order by
  construction: chunk outputs are joined end to end, in chunk order.

## Decision

- `rev-list` runs first. Its hashes, in log order, are the selection.
- When line counts are read and more than one CPU is allowed, the hashes are split into contiguous
  chunks of at least 64 commits, about eight chunks per process, and logged with
  `git log --no-walk=unsorted --stdin --numstat` by at most eight processes at once. Fewer when
  the process may run on fewer CPUs, or a cgroup v2 CPU quota on its cgroup or an ancestor allows
  fewer (rounded up). While the records are taken, a new chunk starts as soon as one ends.
- The hashes go to each process on its standard input, through a pipe.
- Chunk outputs are joined in chunk order, so the records are the bytes one `git log` over the
  same selection gives. The revision and date window are not repeated: `rev-list` applied them.
  Paths are kept, so each commit's file list is limited as before.
- Any chunk that fails fails the read, and every chunk still running is stopped.
- Without line counts (`--name-status`, or none), or with one CPU, one process reads every commit.
- The rest of ADR 0019 stands: `rev-list` is the allowlist, unreadable commits are counted and
  stated, and every read carries the same pinned settings. Never one process per commit.

## Consequences

- Measured on the repository above, `generate --deterministic`, median of five: 6.2 s to 2.2 s with
  20 CPUs; 5.6 s to 3.7 s on two cores (`taskset -c 0,2`); under a 200% CPU quota (systemd
  `CPUQuota=`) 5.5 s and 6.3 s in two runs to 4.3 s. On Reveille's own repository (747 commits) 1.2 s to 0.8 s.
  Sixteen processes were no faster than eight. Not measured on macOS or Windows, where starting a
  process costs more, nor with a cold disk cache.
- Accepted cost: with one CPU (`taskset -c 0`) the read takes 5.6 s instead of 5.5 s, because
  `rev-list` now finishes before the log starts instead of running beside it. Two logical CPUs on
  one core (`taskset -c 0,1`) gained little: 5.5 s to 5.3 s.
- The quota is read because throttled processes are no faster: eight processes under a 200% quota
  took 6.3 s, where one took 5.5 s and 6.3 s in two runs. cgroup v1 quotas are not read; there the count can
  exceed what the quota allows.
- 32 chunks over eight processes took 2.4 s, 64 took 1.1 s, so chunks are kept small against the
  pool. The likely cause is a chunk holding a very large commit holding up its process.
- Up to eight Git processes run at once, each reading the object store; peak CPU use rises with
  them. Reveille's own peak memory (VmHWM) on the repository above went from 78.6 MB to 80.8 MB.
- `--name-status` is not split: on the same repository it took 0.24 s in one process, and at most
  0.1 s less in chunks.

**Confirmation:** `test_chunked_history_read.py::test_chunks_give_the_bytes_one_git_log_gives`
fails if chunk outputs are joined out of order or a chunk drops the paths, and
`test_a_chunk_that_fails_fails_the_read_and_leaves_no_git_running` if a failing chunk is passed
over, `test_no_more_than_the_workers_run_at_once` if the pool is not bounded, and
`test_a_cpu_quota_caps_the_workers` if the quota is not read.
