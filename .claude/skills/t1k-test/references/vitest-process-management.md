---

origin: theonekit-core
repository: The1Studio/theonekit-core
module: t1k-base
protected: true
---
# Vitest Process Management — Reference

Detailed snippets for the two MANDATORY rules in `SKILL.md` → "Invoking Watch-Capable Runners":

1. Kill vitest processes on completion
2. Cap concurrent background vitest runs by device hardware

Loaded on demand — keeps SKILL.md inside the session-context budget.

## Kill sweep — PowerShell (Windows)

```powershell
$pid_root = $VITEST_PID   # captured from Start-Process / Bash run
Stop-Process -Id $pid_root -Force -ErrorAction SilentlyContinue
Get-CimInstance Win32_Process | Where-Object { $_.ParentProcessId -eq $pid_root } |
  ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }
Get-CimInstance Win32_Process |
  Where-Object { $_.Name -eq 'node.exe' -and $_.CommandLine -match 'vitest' } |
  ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }
```

## Kill sweep — Bash (POSIX)

```bash
kill -TERM "$VITEST_PID" 2>/dev/null
pkill -TERM -P "$VITEST_PID" 2>/dev/null
pgrep -af 'node.*vitest' | awk '{print $1}' | xargs -r kill -KILL 2>/dev/null
```

Apply in three places: (1) after every foreground `vitest run` returns, (2) after every `timeout` returns 124, (3) before declaring "done" or starting the next vitest. Wrap in `trap EXIT` (Bash) / try-finally (PowerShell) when scripted.

## Hardware-cap formula

`cap = max(1, min(floor(logicalCores / 4), floor(freeMemGB / 4), 6))`

Rationale: each vitest run spawns its own worker pool (default ≈ `cores/2`) plus main process; one run already saturates ~25% of cores under load. A pool consumes 2-4 GB resident. Ceiling 6 prevents IDE / host paging. Floor 1 keeps low-end boxes functional.

| Logical cores | Free RAM | Cap |
|---|---|---|
| 4  | 8 GB  | 1 |
| 8  | 16 GB | 2 |
| 12 | 24 GB | 3 |
| 16 | 32 GB | 4 |
| 24 | 48 GB | 6 |
| 32 | 64 GB | 6 (ceiling) |

## Compute at session start — PowerShell

```powershell
$cores  = (Get-CimInstance Win32_ComputerSystem).NumberOfLogicalProcessors
$freeKB = (Get-CimInstance Win32_OperatingSystem).FreePhysicalMemory
$freeGB = [math]::Floor($freeKB / 1024 / 1024)
$cap    = [math]::Max(1, [math]::Min([math]::Min([math]::Floor($cores/4), [math]::Floor($freeGB/4)), 6))
```

## Compute at session start — Bash

```bash
cores=$(nproc 2>/dev/null || sysctl -n hw.logicalcpu)
freeKB=$(awk '/MemAvailable/ {print $2}' /proc/meminfo 2>/dev/null || vm_stat | awk '/free/{print $3*4}')
freeGB=$((freeKB / 1024 / 1024))
cap=$(( cores/4 < freeGB/4 ? cores/4 : freeGB/4 ))
[ "$cap" -gt 6 ] && cap=6
[ "$cap" -lt 1 ] && cap=1
```

## Live-count check before launch

```powershell
(Get-CimInstance Win32_Process |
  Where-Object { $_.Name -eq 'node.exe' -and $_.CommandLine -match 'vitest' }).Count
```

```bash
pgrep -af 'node.*vitest' | wc -l
```

If live count ≥ `cap`: STOP — wait for one to finish, or kill the oldest with the sweep above. Do NOT exceed the computed cap. Prefer foreground + timeout. At most `cap - 1` background vitests so a foreground slot remains free.