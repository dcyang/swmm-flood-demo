"""Flask API exposing the real EPA SWMM engine to the Ionic frontend.

Endpoints
  GET  /api/health
  GET  /api/districts                  -> [{id,name_ko,name_en,centroid,blurb,dongs}]
  GET  /api/network/<gu>[/<dong>]      -> topology {nodes, links, marks}
  POST /api/simulate                   -> {topology, ...frames..., summary}
       body: {"gu","dong"?,"rain_mm_h","duration_min"?}

Run a simulation in a single process at a time (SWMM keeps global state); the
runner serializes calls with a lock.
"""

from __future__ import annotations

import os
from functools import lru_cache

from flask import Flask, jsonify, request
from flask_cors import CORS

from engine import networks, runner

app = Flask(__name__)
CORS(app)  # allow the Ionic dev server (and packaged app) to call us


@lru_cache(maxsize=64)
def _topology(gu: str, dong: str | None):
    return networks.build_network(gu, dong)


@app.get("/api/health")
def health():
    return jsonify(status="ok", engine="EPA SWMM 5.2.4", lib=runner.LIB_PATH)


@app.get("/api/districts")
def districts():
    return jsonify(districts=networks.list_districts())


@app.get("/api/network/<gu>")
@app.get("/api/network/<gu>/<dong>")
def network(gu: str, dong: str | None = None):
    try:
        return jsonify(_topology(gu, dong))
    except KeyError as e:
        return jsonify(error=str(e)), 404


@app.post("/api/simulate")
def simulate():
    body = request.get_json(force=True, silent=True) or {}
    gu = body.get("gu")
    dong = body.get("dong") or None
    if not gu:
        return jsonify(error="'gu' is required"), 400
    try:
        rain = float(body.get("rain_mm_h", 60))
    except (TypeError, ValueError):
        return jsonify(error="'rain_mm_h' must be a number"), 400
    rain = max(0.0, min(400.0, rain))
    duration = float(body.get("duration_min", 45))
    duration = max(5.0, min(240.0, duration))

    try:
        topo = _topology(gu, dong)
    except KeyError as e:
        return jsonify(error=str(e)), 404

    try:
        result = runner.simulate(topo, rain_mm_h=rain, duration_min=duration)
    except runner.SwmmError as e:
        return jsonify(error=f"simulation failed: {e}"), 500

    result["topology"] = topo
    result["gu"] = gu
    result["dong"] = dong
    return jsonify(result)


if __name__ == "__main__":
    # Bind to 127.0.0.1 by default; set FLASK_HOST=0.0.0.0 to expose publicly.
    # Keep debug OFF when exposed (the Werkzeug debugger allows remote code exec).
    host = os.environ.get("FLASK_HOST", "127.0.0.1")
    port = int(os.environ.get("FLASK_PORT", "5057"))
    debug = os.environ.get("FLASK_DEBUG", "0") == "1"
    app.run(host=host, port=port, debug=debug)
