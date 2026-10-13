"""Best-effort peak memory measurement for the parse pipeline.

Windows: process working-set peak via psapi (ctypes, stdlib only).
Other platforms: returns None (documented limitation, not a fabricated value).
"""

from __future__ import annotations

import ctypes
import sys

_PROCESS_QUERY_LIMITED_INFORMATION = 0x1000


class _PROCESS_MEMORY_COUNTERS(ctypes.Structure):
    _fields_ = [
        ("cb", ctypes.c_ulong),
        ("PageFaultCount", ctypes.c_ulong),
        ("PeakWorkingSetSize", ctypes.c_size_t),
        ("WorkingSetSize", ctypes.c_size_t),
        ("QuotaPeakPagedPoolUsage", ctypes.c_size_t),
        ("QuotaPagedPoolUsage", ctypes.c_size_t),
        ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t),
        ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
        ("PagefileUsage", ctypes.c_size_t),
        ("PeakPagefileUsage", ctypes.c_size_t),
    ]


def get_memory_info_mb(pid: int) -> tuple[float | None, float | None]:
    """(current, peak) working set (MB) of a process; (None, None) if unavailable."""
    if sys.platform != "win32":
        return None, None
    try:
        k32 = ctypes.windll.kernel32
        psapi = ctypes.windll.psapi
        handle = k32.OpenProcess(_PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
        if not handle:
            return None, None
        try:
            counters = _PROCESS_MEMORY_COUNTERS()
            counters.cb = ctypes.sizeof(_PROCESS_MEMORY_COUNTERS)
            if not psapi.GetProcessMemoryInfo(handle, ctypes.byref(counters), counters.cb):
                return None, None
            return (
                counters.WorkingSetSize / (1024.0 * 1024.0),
                counters.PeakWorkingSetSize / (1024.0 * 1024.0),
            )
        finally:
            k32.CloseHandle(handle)
    except Exception:
        return None, None


def get_peak_memory_mb(pid: int) -> float | None:
    """Peak working set (MB) of a process, or None when unavailable."""
    return get_memory_info_mb(pid)[1]


def get_self_peak_memory_mb() -> float | None:
    """Peak working set (MB) of the current process, or None."""
    if sys.platform != "win32":
        return None
    try:
        psapi = ctypes.windll.psapi
        counters = _PROCESS_MEMORY_COUNTERS()
        counters.cb = ctypes.sizeof(_PROCESS_MEMORY_COUNTERS)
        handle = ctypes.windll.kernel32.GetCurrentProcess()
        if not psapi.GetProcessMemoryInfo(handle, ctypes.byref(counters), counters.cb):
            return None
        return counters.PeakWorkingSetSize / (1024.0 * 1024.0)
    except Exception:
        return None
