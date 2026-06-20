"""ctypes driver for the real EPA SWMM solver (libswmm5.so).

Runs a simulation step-by-step and samples node/link/system state into frames
suitable for animation in the frontend. This loads the user's *built* shared
library directly (no rebuild, no Python toolkit needed) and mirrors the call
sequence in EPA's reference ``swmm5.py`` / ``src/run/main.c``.
"""

from __future__ import annotations

import ctypes
import os
import tempfile
import threading
from typing import Optional

from . import inp_builder

# ---- libswmm5.so location ------------------------------------------------
_DEFAULT_LIB = os.path.abspath(os.path.join(
    os.path.dirname(__file__), "..", "..", "..",
    "Stormwater-Management-Model", "build", "bin", "libswmm5.so"))
LIB_PATH = os.environ.get("SWMM_LIB", _DEFAULT_LIB)

# SWMM object types (swmm5.h enum swmm_Object)
_GAGE, _SUBCATCH, _NODE, _LINK, _SYSTEM = 0, 1, 2, 3, 4

# Node/link property codes (swmm5.h enums)
_NODE_DEPTH = 303
_NODE_LATFLOW = 306
_NODE_INFLOW = 307
_NODE_OVERFLOW = 308
_LINK_FLOW = 410
_LINK_DEPTH = 411

# SWMM keeps global state, so only one simulation may run at a time per process.
_RUN_LOCK = threading.Lock()
_lib: Optional[ctypes.CDLL] = None


def _load() -> ctypes.CDLL:
    global _lib
    if _lib is None:
        lib = ctypes.CDLL(LIB_PATH)
        lib.swmm_open.argtypes = [ctypes.c_char_p, ctypes.c_char_p, ctypes.c_char_p]
        lib.swmm_open.restype = ctypes.c_int
        lib.swmm_start.argtypes = [ctypes.c_int]
        lib.swmm_start.restype = ctypes.c_int
        lib.swmm_step.argtypes = [ctypes.POINTER(ctypes.c_double)]
        lib.swmm_step.restype = ctypes.c_int
        lib.swmm_end.restype = ctypes.c_int
        lib.swmm_close.restype = ctypes.c_int
        lib.swmm_getCount.argtypes = [ctypes.c_int]
        lib.swmm_getCount.restype = ctypes.c_int
        lib.swmm_getName.argtypes = [ctypes.c_int, ctypes.c_int, ctypes.c_char_p, ctypes.c_int]
        lib.swmm_getIndex.argtypes = [ctypes.c_int, ctypes.c_char_p]
        lib.swmm_getIndex.restype = ctypes.c_int
        lib.swmm_getValue.argtypes = [ctypes.c_int, ctypes.c_int]
        lib.swmm_getValue.restype = ctypes.c_double
        lib.swmm_getError.argtypes = [ctypes.c_char_p, ctypes.c_int]
        lib.swmm_getError.restype = ctypes.c_int
        lib.swmm_getMassBalErr.argtypes = [ctypes.POINTER(ctypes.c_float)] * 3
        lib.swmm_getMassBalErr.restype = ctypes.c_int
        _lib = lib
    return _lib


def _name(lib, otype: int, idx: int) -> str:
    buf = ctypes.create_string_buffer(80)
    lib.swmm_getName(otype, idx, buf, 80)
    return buf.value.decode("ascii", "replace")


class SwmmError(RuntimeError):
    pass


def simulate(topology: dict, rain_mm_h: float, duration_min: float = 45.0,
             total_min: float | None = None, max_frames: int = 240,
             sample_sec: float = 45.0) -> dict:
    """Run a full SWMM simulation for ``topology`` and return frames + summary.

    Returns::

        {
          "rain_mm_h", "duration_min",
          "node_ids": [...], "link_ids": [...],
          "frames": [
            {"t": sec,
             "nodes": [{"depth","flood","fillRatio"}...],   # aligned to node_ids
             "links": [{"flow","fill"}...],                 # aligned to link_ids
             "sys": {"inflow","outflow","flooding"}},
            ...
          ],
          "summary": {"flood_nodes","total_flood_m3","peak_outflow_cms",
                      "peak_depth_m","mass_balance_error_pct"}
        }
    """
    inp_text = inp_builder.build_inp(topology, rain_mm_h, duration_min, total_min)

    node_full = {n["id"]: n["full"] for n in topology["nodes"]}
    outfall_ids = {n["id"] for n in topology["nodes"] if n["outfall"]}
    link_D = {lk["id"]: lk["D"] for lk in topology["links"]}

    with _RUN_LOCK:
        lib = _load()
        workdir = tempfile.mkdtemp(prefix="swmm_")
        inp = os.path.join(workdir, "model.inp")
        rpt = os.path.join(workdir, "model.rpt")
        out = os.path.join(workdir, "model.out")
        with open(inp, "w") as f:
            f.write(inp_text)

        def _check(code: int, where: str):
            if code != 0:
                buf = ctypes.create_string_buffer(256)
                lib.swmm_getError(buf, 256)
                msg = buf.value.decode("ascii", "replace").strip()
                raise SwmmError(f"SWMM {where} failed (code {code}): {msg}")

        b = inp.encode(); r = rpt.encode(); o = out.encode()
        _check(lib.swmm_open(b, r, o), "open")
        try:
            _check(lib.swmm_start(0), "start")  # 0 = don't write binary .out

            n_nodes = lib.swmm_getCount(_NODE)
            n_links = lib.swmm_getCount(_LINK)
            node_names = [_name(lib, _NODE, i) for i in range(n_nodes)]
            link_names = [_name(lib, _LINK, i) for i in range(n_links)]
            node_idx = {nm: i for i, nm in enumerate(node_names)}
            outfall_pos = [node_idx[nm] for nm in node_names if nm in outfall_ids]

            frames: list[dict] = []
            flood_vol = {nm: 0.0 for nm in node_names}
            peak_depth = 0.0
            peak_out = 0.0
            ever_flooded: set[str] = set()

            elapsed = ctypes.c_double(0.0)
            prev_days = 0.0
            next_sample = 0.0
            t_sec = 0.0
            steps = 0
            while True:
                _check(lib.swmm_step(ctypes.byref(elapsed)), "step")
                steps += 1
                days = elapsed.value
                if days <= 0.0:
                    break
                dt = max(0.0, (days - prev_days) * 86400.0)
                prev_days = days
                t_sec = days * 86400.0

                # accumulate flood volume + peaks every routing step
                sys_out = 0.0
                for pos in outfall_pos:
                    sys_out += lib.swmm_getValue(_NODE_INFLOW, pos)
                peak_out = max(peak_out, sys_out)
                for i, nm in enumerate(node_names):
                    ov = lib.swmm_getValue(_NODE_OVERFLOW, i)
                    if ov > 0:
                        flood_vol[nm] += ov * dt
                        if ov > 0.002:
                            ever_flooded.add(nm)
                    d = lib.swmm_getValue(_NODE_DEPTH, i)
                    if nm not in outfall_ids and d > peak_depth:
                        peak_depth = d

                # sample a frame at the reporting cadence
                if t_sec >= next_sample:
                    next_sample = t_sec + sample_sec
                    nrec = []
                    sys_in = 0.0
                    sys_flood = 0.0
                    for i, nm in enumerate(node_names):
                        depth = lib.swmm_getValue(_NODE_DEPTH, i)
                        flood = lib.swmm_getValue(_NODE_OVERFLOW, i)
                        lat = lib.swmm_getValue(_NODE_LATFLOW, i)
                        sys_in += max(0.0, lat)
                        sys_flood += max(0.0, flood)
                        full = node_full.get(nm, 1.0) or 1.0
                        fr = 0.0 if nm in outfall_ids else min(1.0, depth / full)
                        nrec.append({"depth": round(depth, 3),
                                     "flood": round(flood, 4),
                                     "fillRatio": round(fr, 3)})
                    lrec = []
                    for i, nm in enumerate(link_names):
                        flow = lib.swmm_getValue(_LINK_FLOW, i)
                        ldepth = lib.swmm_getValue(_LINK_DEPTH, i)
                        D = link_D.get(nm, 1.0) or 1.0
                        lrec.append({"flow": round(flow, 4),
                                     "fill": round(min(1.0, ldepth / D), 3)})
                    frames.append({
                        "t": round(t_sec, 1),
                        "nodes": nrec, "links": lrec,
                        "sys": {"inflow": round(sys_in, 4),
                                "outflow": round(sys_out, 4),
                                "flooding": round(sys_flood, 4)},
                    })
                    if len(frames) >= max_frames:
                        break

            runoff_e = ctypes.c_float(0.0)
            flow_e = ctypes.c_float(0.0)
            qual_e = ctypes.c_float(0.0)
            lib.swmm_getMassBalErr(ctypes.byref(runoff_e),
                                   ctypes.byref(flow_e), ctypes.byref(qual_e))
            lib.swmm_end()
        finally:
            lib.swmm_close()

        # cleanup temp files
        for p in (inp, rpt, out):
            try:
                os.remove(p)
            except OSError:
                pass
        try:
            os.rmdir(workdir)
        except OSError:
            pass

    total_flood = sum(flood_vol.values())
    return {
        "rain_mm_h": rain_mm_h,
        "duration_min": duration_min,
        "node_ids": node_names,
        "link_ids": link_names,
        "frames": frames,
        "summary": {
            "flood_nodes": len(ever_flooded),
            "total_flood_m3": round(total_flood, 1),
            "peak_outflow_cms": round(peak_out, 3),
            "peak_depth_m": round(peak_depth, 3),
            "mass_balance_error_pct": round(float(flow_e.value), 3),
        },
    }
