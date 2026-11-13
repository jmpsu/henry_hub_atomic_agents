"""Build web/data/na_basemap.json: North American wireframe linework shared by the web map and the terminal Braille map.
Inputs (downloaded once at build time, not used at runtime): us-atlas states-10m.json (US Census, ISC licence wrapper) and
world-atlas countries-50m.json (Natural Earth, public domain). Output: {"bbox": [...], "layers": {"coast_and_borders": [...], "states": [...]}}
where each layer is a list of polylines [[lon, lat], ...] clipped to the bbox and thinned to ~0.03 degrees."""
import json
import sys
from pathlib import Path

BBOX = (-128.0, 22.0, -64.0, 53.0)   # west, south, east, north
KEEP_COUNTRIES = {"840", "124", "484", "192", "044"}   # USA, Canada, Mexico, Cuba, Bahamas


def decode(topo):
    sx, sy = topo["transform"]["scale"]
    tx, ty = topo["transform"]["translate"]
    out = []
    for arc in topo["arcs"]:
        x = y = 0
        pts = []
        for dx, dy in arc:
            x += dx
            y += dy
            pts.append((x * sx + tx, y * sy + ty))
        out.append(pts)
    return out


def arc_ids(geom):
    ids = set()

    def walk(a):
        for v in a:
            if isinstance(v, list):
                walk(v)
            else:
                ids.add(v if v >= 0 else ~v)
    walk(geom.get("arcs", []))
    return ids


def clip_thin(pts, step=0.03):
    w, s, e, n = BBOX
    runs, cur, last = [], [], None
    for lon, lat in pts:
        if w <= lon <= e and s <= lat <= n:
            if last is None or abs(lon - last[0]) >= step or abs(lat - last[1]) >= step:
                cur.append([round(lon, 3), round(lat, 3)])
                last = (lon, lat)
        else:
            if len(cur) > 1:
                runs.append(cur)
            cur, last = [], None
    if len(cur) > 1:
        runs.append(cur)
    return runs


def main(states_path, countries_path, out_path):
    states = json.loads(Path(states_path).read_text())
    world = json.loads(Path(countries_path).read_text())
    s_arcs, w_arcs = decode(states), decode(world)
    state_ids = set()
    for g in states["objects"]["states"]["geometries"]:
        state_ids |= arc_ids(g)
    country_ids = set()
    for g in world["objects"]["countries"]["geometries"]:
        if str(g.get("id")) in KEEP_COUNTRIES:
            country_ids |= arc_ids(g)
    layers = {"states": [r for i in sorted(state_ids) for r in clip_thin(s_arcs[i])],
              "coast_and_borders": [r for i in sorted(country_ids) for r in clip_thin(w_arcs[i], 0.05)]}
    Path(out_path).write_text(json.dumps({"bbox": list(BBOX), "layers": layers,
                                          "attribution": "US Census cartographic boundaries via us-atlas; Natural Earth via world-atlas"}, separators=(",", ":")))
    print({k: (len(v), sum(len(x) for x in v)) for k, v in layers.items()}, Path(out_path).stat().st_size, "bytes")


if __name__ == "__main__":
    main(*sys.argv[1:4])
