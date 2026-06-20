"""Synthetic Seoul drainage-network generator.

This is a Python port of the procedural network builder in ``gangnam.html``
(``buildNetwork()``), generalized so each 구(gu)/동(dong) gets its own distinct
but deterministic network. The same topology produced here feeds both the SWMM
``.inp`` builder and the ``/api/network`` response, so what the app draws is
exactly what the engine simulates.

Topology dict returned by :func:`build_network`::

    {
      "id": "gangnam",                 # district key
      "title": "서울 강남구 ...",
      "nodes": [
        {"id","nx","ny","xm","ym","ground","invert","full","area",
         "outfall": bool, "sub": {"area","imp"} | None}, ...
      ],
      "links": [{"id","f","t","D","L","n"}, ...],
      "marks": [{"n","x","y"}, ...],    # landmarks for context
    }

Coordinates: ``nx,ny`` are normalized [0,1] for rendering; ``xm,ym`` are meters
for the SWMM ``[COORDINATES]`` section.
"""

from __future__ import annotations

import math
from collections import deque
from typing import Optional

# Standard nominal pipe / box-culvert diameters (m), as in gangnam.html
NOMINAL = [0.3, 0.4, 0.5, 0.6, 0.8, 1.0, 1.2, 1.5, 1.8, 2.0, 2.4, 3.0, 3.5]


def _hash(n: float, seed: float) -> float:
    """Deterministic [0,1) hash (no RNG), matching gangnam.html's hash()."""
    s = math.sin((n + seed * 1000.0) * 127.1 + 311.7) * 43758.5453
    return s - math.floor(s)


def _ground(gx: float, gy: float, p: dict) -> float:
    """Synthetic DEM. gx:0(W)->1(E), gy:0(N,river)->1(S,hills).

    Parameterized version of gangnam.html's ground() so each district has its
    own basin / ridge layout.
    """
    e = p["base"]
    e += p["south_rise"] * gy
    e += p["west_rise"] * (1 - gx) * (0.6 + 0.4 * gy)
    e += p["ridge"] * math.pow(max(0.0, (gy - 0.62) / 0.38), 1.6)
    bx, by = p["basin"]
    e -= p["basin_depth"] * math.exp(-(((gx - bx) ** 2) / 0.020 + ((gy - by) ** 2) / 0.034))
    e -= p["valley"] * math.exp(-(((gy - 0.42) ** 2) / 0.05)) * gx
    return e


def _build_grid_network(
    *,
    key: str,
    title: str,
    GX: int,
    GY: int,
    cell: float,
    slope: float,
    outfalls: list[tuple[int, int]],
    ground_params: dict,
    seed: float,
    marks: Optional[list[dict]] = None,
) -> dict:
    """Core procedural builder (faithful port of buildNetwork())."""
    def gid(i: int, j: int) -> str:
        return f"N{i}_{j}"

    def in_grid(i: int, j: int) -> bool:
        return 0 <= i < GX and 0 <= j < GY

    out_set = {(i, j) for (i, j) in outfalls}
    nodes: dict[str, dict] = {}
    node_list: list[dict] = []

    # 1) nodes over the grid, with deterministic jitter
    for j in range(GY):
        for i in range(GX):
            gx = i / (GX - 1)
            gy = j / (GY - 1)
            jx = (_hash(i * 7 + j * 13, seed) - 0.5) * 0.6
            jy = (_hash(i * 17 + j * 5, seed) - 0.5) * 0.6
            is_out = (i, j) in out_set
            nd = {
                "id": gid(i, j), "i": i, "j": j,
                "xm": (i + jx) * cell, "ym": (j + jy) * cell,
                "nx": gx, "ny": gy,
                "ground": _ground(gx, gy, ground_params),
                "outfall": is_out, "grid_outfall": is_out,
            }
            nodes[nd["id"]] = nd
            node_list.append(nd)

    # 2) multi-source BFS distance from outfalls
    dist: dict[str, int] = {}
    q: deque[str] = deque()
    for (i, j) in outfalls:
        nid = gid(i, j)
        dist[nid] = 0
        q.append(nid)

    def nbrs(nd: dict) -> list[dict]:
        out = []
        for di, dj in ((1, 0), (-1, 0), (0, 1), (0, -1)):
            ni, nj = nd["i"] + di, nd["j"] + dj
            if in_grid(ni, nj):
                out.append(nodes[gid(ni, nj)])
        return out

    while q:
        cur = nodes[q.popleft()]
        for nb in nbrs(cur):
            if nb["id"] not in dist:
                dist[nb["id"]] = dist[cur["id"]] + 1
                q.append(nb["id"])

    # 3) downstream pointer: smaller-distance neighbor with lowest ground
    for nd in node_list:
        nd["dist"] = dist[nd["id"]]
        nd["down"] = None
        nd["acc"] = 1
    for nd in node_list:
        if nd["outfall"]:
            continue
        best = None
        for nb in nbrs(nd):
            if dist[nb["id"]] < dist[nd["id"]]:
                if best is None or nb["ground"] < best["ground"]:
                    best = nb
        nd["down"] = best

    # 4) accumulate upstream node count (~drainage area) upstream->downstream
    for nd in sorted(node_list, key=lambda n: -n["dist"]):
        if nd["down"]:
            nd["down"]["acc"] += nd["acc"]

    # 5) grade inverts downstream->upstream with a minimum slope
    for nd in sorted(node_list, key=lambda n: n["dist"]):
        if nd["outfall"]:
            nd["invert"] = nd["ground"] - 4.0
            continue
        d = nd["down"]
        length = math.hypot(nd["xm"] - d["xm"], nd["ym"] - d["ym"])
        nd["_len"] = length
        nd["invert"] = d["invert"] + slope * length

    # 6) links + pipe sizing + subcatchments
    links: list[dict] = []
    for nd in node_list:
        if nd["outfall"]:
            continue
        d = nd["down"]
        length = nd["_len"]
        D = 0.35 + 0.27 * math.sqrt(nd["acc"])
        D = min(NOMINAL, key=lambda c: abs(c - D))
        links.append({"id": f"C_{nd['id']}", "f": nd["id"], "t": d["id"],
                      "D": D, "L": max(length, 10.0), "n": 0.013})
        nd["full"] = max(1.5, min(6.0, nd["ground"] - nd["invert"]))
        nd["area"] = 60 + 90 * max(0.0, (20 - nd["ground"])) / 20 + 0.6 * nd["acc"]
        nd["sub"] = {"area": cell * cell * 1.15,
                     "imp": 0.74 + 0.06 * _hash(nd["i"] * 3 + nd["j"], seed)}
    # SWMM requires each OUTFALL to be a terminal node with exactly one inlet
    # link. The grid boundary cells collect several conduits, so keep them as
    # discharge JUNCTIONS and hang a dedicated terminal outfall off each one.
    terminals: list[dict] = []
    for nd in node_list:
        if not nd["grid_outfall"]:
            continue
        nd["outfall"] = False
        nd["full"] = max(1.5, min(6.0, nd["ground"] - nd["invert"]))
        nd["area"] = 200.0
        nd["sub"] = None
        # outward offset based on which border this cell sits on
        dx = (-1 if nd["i"] == 0 else 1 if nd["i"] == GX - 1 else 0)
        dy = (-1 if nd["j"] == 0 else 1 if nd["j"] == GY - 1 else 0)
        if dx == 0 and dy == 0:
            dy = -1
        of_invert = nd["invert"] - 1.0
        of = {
            "id": f"OF_{nd['id']}", "i": -1, "j": -1,
            "xm": nd["xm"] + dx * cell * 0.6, "ym": nd["ym"] + dy * cell * 0.6,
            "nx": max(-0.03, min(1.03, nd["nx"] + dx * 0.045)),
            "ny": max(-0.03, min(1.03, nd["ny"] + dy * 0.045)),
            "ground": nd["ground"] - 1.0, "invert": of_invert,
            "full": 99.0, "area": 300.0, "outfall": True, "grid_outfall": False,
            "sub": None,
        }
        D = 0.35 + 0.27 * math.sqrt(nd["acc"])
        D = min(NOMINAL, key=lambda c: abs(c - max(1.0, D)))
        links.append({"id": f"C_OF_{nd['id']}", "f": nd["id"], "t": of["id"],
                      "D": D, "L": cell * 0.6, "n": 0.013})
        terminals.append(of)
    node_list.extend(terminals)

    # public, JSON-friendly node records
    pub_nodes = []
    for nd in node_list:
        pub_nodes.append({
            "id": nd["id"], "nx": round(nd["nx"], 4), "ny": round(nd["ny"], 4),
            "xm": round(nd["xm"], 2), "ym": round(nd["ym"], 2),
            "ground": round(nd["ground"], 3), "invert": round(nd["invert"], 3),
            "full": round(nd["full"], 3), "area": round(nd["area"], 2),
            "outfall": nd["outfall"],
            "sub": (None if nd.get("sub") is None
                    else {"area": round(nd["sub"]["area"], 1),
                          "imp": round(nd["sub"]["imp"], 3)}),
        })

    return {
        "id": key, "title": title,
        "nodes": pub_nodes, "links": links,
        "marks": marks or [],
    }


# --------------------------------------------------------------------------
# District registry — a few representative 구 (start small per the plan).
# Each gu has a gu-level network plus a few 동 (smaller sub-networks).
# --------------------------------------------------------------------------

_GANGNAM_GROUND = {
    "base": 12, "south_rise": 23, "west_rise": 7, "ridge": 9,
    "basin": (0.27, 0.58), "basin_depth": 16, "valley": 4,
}
_GANGNAM_MARKS = [
    {"n": "강남역", "x": 0.27, "y": 0.58}, {"n": "역삼역", "x": 0.44, "y": 0.46},
    {"n": "선릉역", "x": 0.58, "y": 0.40}, {"n": "삼성역", "x": 0.74, "y": 0.36},
]

DISTRICTS: dict[str, dict] = {
    "gangnam": {
        "name_ko": "강남구", "name_en": "Gangnam-gu",
        "centroid": [37.5172, 127.0473],
        "blurb": "강남역 분지(저지대) + 남측 구릉, 한강(북)/탄천(동) 방류",
        "grid": (12, 9), "cell": 165, "slope": 0.0032, "seed": 0.0,
        "outfalls": [(3, 0), (7, 0), (10, 0), (11, 2), (11, 5)],
        "ground": _GANGNAM_GROUND, "marks": _GANGNAM_MARKS,
        "dongs": [
            {"id": "yeoksam", "name_ko": "역삼동", "name_en": "Yeoksam-dong"},
            {"id": "samseong", "name_ko": "삼성동", "name_en": "Samseong-dong"},
            {"id": "daechi", "name_ko": "대치동", "name_en": "Daechi-dong"},
        ],
    },
    "seocho": {
        "name_ko": "서초구", "name_en": "Seocho-gu",
        "centroid": [37.4837, 127.0324],
        "blurb": "우면산 남고지 + 반포 저지대, 한강(북) 방류",
        "grid": (11, 9), "cell": 175, "slope": 0.0030, "seed": 17.0,
        "outfalls": [(2, 0), (5, 0), (8, 0), (10, 3)],
        "ground": {"base": 14, "south_rise": 28, "west_rise": 5, "ridge": 12,
                   "basin": (0.5, 0.5), "basin_depth": 13, "valley": 3},
        "marks": [{"n": "서초역", "x": 0.45, "y": 0.5}, {"n": "교대역", "x": 0.6, "y": 0.46},
                  {"n": "반포", "x": 0.4, "y": 0.2}],
        "dongs": [
            {"id": "seocho", "name_ko": "서초동", "name_en": "Seocho-dong"},
            {"id": "banpo", "name_ko": "반포동", "name_en": "Banpo-dong"},
            {"id": "bangbae", "name_ko": "방배동", "name_en": "Bangbae-dong"},
        ],
    },
    "songpa": {
        "name_ko": "송파구", "name_en": "Songpa-gu",
        "centroid": [37.5145, 127.1060],
        "blurb": "비교적 평탄한 저지대, 석촌호수/탄천·한강 방류",
        "grid": (12, 8), "cell": 180, "slope": 0.0028, "seed": 41.0,
        "outfalls": [(0, 2), (0, 5), (4, 0), (8, 0), (11, 4)],
        "ground": {"base": 11, "south_rise": 14, "west_rise": 4, "ridge": 5,
                   "basin": (0.45, 0.5), "basin_depth": 9, "valley": 5},
        "marks": [{"n": "잠실역", "x": 0.3, "y": 0.3}, {"n": "석촌호수", "x": 0.35, "y": 0.45},
                  {"n": "문정", "x": 0.6, "y": 0.7}],
        "dongs": [
            {"id": "jamsil", "name_ko": "잠실동", "name_en": "Jamsil-dong"},
            {"id": "garak", "name_ko": "가락동", "name_en": "Garak-dong"},
            {"id": "munjeong", "name_ko": "문정동", "name_en": "Munjeong-dong"},
        ],
    },
}


def list_districts() -> list[dict]:
    """Lightweight metadata for all supported districts (for /api/districts)."""
    out = []
    for key, d in DISTRICTS.items():
        out.append({
            "id": key, "name_ko": d["name_ko"], "name_en": d["name_en"],
            "centroid": d["centroid"], "blurb": d["blurb"],
            "dongs": d["dongs"],
        })
    return out


def build_network(gu: str, dong: Optional[str] = None) -> dict:
    """Build the topology for a gu, or a smaller sub-network for one of its dong."""
    if gu not in DISTRICTS:
        raise KeyError(f"unknown gu: {gu}")
    d = DISTRICTS[gu]
    GX, GY = d["grid"]

    if dong is None:
        return _build_grid_network(
            key=gu, title=f"서울 {d['name_ko']} 우수관망",
            GX=GX, GY=GY, cell=d["cell"], slope=d["slope"],
            outfalls=d["outfalls"], ground_params=d["ground"],
            seed=d["seed"], marks=d["marks"],
        )

    # dong-level: a smaller neighborhood sub-network with its own seed + single outfall
    dong_ids = [x["id"] for x in d["dongs"]]
    if dong not in dong_ids:
        raise KeyError(f"unknown dong: {dong} in {gu}")
    idx = dong_ids.index(dong)
    name_ko = d["dongs"][idx]["name_ko"]
    sgx, sgy = max(6, GX - 4), max(5, GY - 3)
    return _build_grid_network(
        key=f"{gu}:{dong}", title=f"서울 {d['name_ko']} {name_ko}",
        GX=sgx, GY=sgy, cell=d["cell"] * 0.7, slope=d["slope"],
        outfalls=[(sgx // 2, 0)],
        ground_params=d["ground"], seed=d["seed"] + 100.0 * (idx + 1),
        marks=[],
    )
