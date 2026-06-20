"""Generate a SWMM 5.2 ``.inp`` input file from a topology dict + a rain storm.

Units are SI/metric (FLOW_UNITS CMS) to match the in-browser demos: rainfall in
mm/hr, lengths in m, subcatchment area in ha, flows in m^3/s. Routing is full
dynamic wave (DYNWAVE) — the algorithm the demos approximate.
"""

from __future__ import annotations


def _hhmm(total_minutes: float) -> str:
    """Format minutes as H:MM (SWMM time-of-series / clock format, hours may exceed 24)."""
    h = int(total_minutes // 60)
    m = int(round(total_minutes - h * 60))
    if m == 60:
        h += 1
        m = 0
    return f"{h}:{m:02d}"


def build_inp(topology: dict, rain_mm_h: float, duration_min: float = 60.0,
              total_min: float | None = None) -> str:
    """Return the full text of a SWMM .inp file.

    rain_mm_h    constant rainfall intensity during the storm
    duration_min storm length; rain is 0 afterwards so the network can drain
    total_min    total simulation length (defaults to duration + 120 min drain)
    """
    nodes = topology["nodes"]
    links = topology["links"]
    if total_min is None:
        total_min = duration_min + 90.0

    L: list[str] = []
    w = L.append

    w("[TITLE]")
    w(topology.get("title", "SWMM auto-generated network"))
    w("")

    w("[OPTIONS]")
    w("FLOW_UNITS           CMS")
    w("INFILTRATION         HORTON")
    w("FLOW_ROUTING         DYNWAVE")
    w("LINK_OFFSETS         DEPTH")
    w("MIN_SLOPE            0")
    w("ALLOW_PONDING        NO")
    w("SKIP_STEADY_STATE    NO")
    w("START_DATE           01/01/2024")
    w("START_TIME           00:00:00")
    w("REPORT_START_DATE    01/01/2024")
    w("REPORT_START_TIME    00:00:00")
    end_day = 1 + int(total_min // 1440)
    rem = total_min - int(total_min // 1440) * 1440
    eh = int(rem // 60)
    em = int(round(rem - eh * 60))
    if em == 60:
        eh += 1
        em = 0
    w(f"END_DATE             01/{end_day:02d}/2024")
    w(f"END_TIME             {eh:02d}:{em:02d}:00")
    w("REPORT_STEP          00:00:30")
    w("WET_STEP             00:00:15")
    w("DRY_STEP             00:01:00")
    w("ROUTING_STEP         2")
    w("INERTIAL_DAMPING     PARTIAL")
    w("NORMAL_FLOW_LIMITED  BOTH")
    w("FORCE_MAIN_EQUATION  H-W")
    w("VARIABLE_STEP        0.75")
    w("LENGTHENING_STEP     0")
    w("MIN_SURFAREA         1.14")
    w("MAX_TRIALS           8")
    w("HEAD_TOLERANCE       0.0015")
    w("SYS_FLOW_TOL         5")
    w("LAT_FLOW_TOL         5")
    w("")

    w("[EVAPORATION]")
    w("CONSTANT     0.0")
    w("DRY_ONLY     NO")
    w("")

    w("[RAINGAGES]")
    w(";;Name   Format    Interval  SCF   Source")
    w("RG1      INTENSITY 0:05      1.0   TIMESERIES TS_RAIN")
    w("")

    w("[TIMESERIES]")
    w(";;Name   Time    Value (mm/hr)")
    # Emit at the 5-min gage recording interval so the constant storm is
    # unambiguous (and SWMM doesn't warn about a coarse series interval).
    t = 0.0
    while t < duration_min - 1e-6:
        w(f"TS_RAIN  {_hhmm(t)}    {rain_mm_h:.3f}")
        t += 5.0
    w(f"TS_RAIN  {_hhmm(duration_min)}    0.0")
    w(f"TS_RAIN  {_hhmm(total_min)}    0.0")
    w("")

    # Subcatchments (one per junction that has a sub), draining to that node
    w("[SUBCATCHMENTS]")
    w(";;Name     RainGage  Outlet    Area_ha  %Imperv  Width_m  Slope_%  CurbLen")
    for nd in nodes:
        sub = nd.get("sub")
        if not sub:
            continue
        area_ha = sub["area"] / 10000.0
        width = max(5.0, (sub["area"] ** 0.5))
        w(f"S_{nd['id']:<8} RG1      {nd['id']:<9} {area_ha:8.4f} "
          f"{sub['imp'] * 100:7.2f} {width:8.1f} {1.0:7.2f}  0")
    w("")

    w("[SUBAREAS]")
    w(";;Subcatch  N_Imp  N_Perv  S_Imp  S_Perv  %Zero  RouteTo")
    for nd in nodes:
        if not nd.get("sub"):
            continue
        w(f"S_{nd['id']:<8} 0.013  0.10    1.5    5.0     25     OUTLET")
    w("")

    w("[INFILTRATION]")
    w(";;Subcatch  MaxRate  MinRate  Decay  DryTime  MaxInfil")
    for nd in nodes:
        if not nd.get("sub"):
            continue
        w(f"S_{nd['id']:<8} 8.0      4.0      4.0    7.0      0")
    w("")

    w("[JUNCTIONS]")
    w(";;Name     Elev     MaxDepth  InitDepth  SurDepth  Aponded")
    for nd in nodes:
        if nd["outfall"]:
            continue
        w(f"{nd['id']:<9} {nd['invert']:8.3f} {nd['full']:8.3f} 0          0         0")
    w("")

    w("[OUTFALLS]")
    w(";;Name     Elev     Type   Stage  Gated")
    for nd in nodes:
        if nd["outfall"]:
            w(f"{nd['id']:<9} {nd['invert']:8.3f} FREE          NO")
    w("")

    w("[CONDUITS]")
    w(";;Name     Node1     Node2     Length   Rough   InOff  OutOff  InitFlow  MaxFlow")
    for lk in links:
        w(f"{lk['id']:<9} {lk['f']:<9} {lk['t']:<9} {lk['L']:8.2f} "
          f"{lk['n']:6.3f}  0      0       0         0")
    w("")

    w("[XSECTIONS]")
    w(";;Link     Shape     Geom1   Geom2  Geom3  Geom4  Barrels")
    for lk in links:
        w(f"{lk['id']:<9} CIRCULAR  {lk['D']:6.3f}  0      0      0      1")
    w("")

    w("[REPORT]")
    w("INPUT       NO")
    w("CONTINUITY  YES")
    w("FLOWSTATS   YES")
    w("NODES       ALL")
    w("LINKS       ALL")
    w("")

    w("[COORDINATES]")
    w(";;Node     X_m       Y_m")
    for nd in nodes:
        w(f"{nd['id']:<9} {nd['xm']:10.2f} {nd['ym']:10.2f}")
    w("")

    return "\n".join(L) + "\n"
