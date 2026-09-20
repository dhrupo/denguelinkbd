import json
from dataclasses import dataclass
from itertools import combinations

import numpy as np

NEIGHBOUR_DEG = 0.01


@dataclass
class Areas:
    districts: list[str]
    upazila_name: dict[str, str]
    upazila_district: dict[str, str]
    neighbours: dict[str, set[str]]
    centroid: dict[str, tuple[float, float]]
    district_division: dict[str, str]
    division_neighbours: dict[str, set[str]]
    division_centroid: dict[str, tuple[float, float]]


def _outer_rings(geometry):
    polys = geometry["coordinates"] if geometry["type"] == "MultiPolygon" else [geometry["coordinates"]]
    return [np.asarray(p[0], dtype=float) for p in polys]


def _inside(points, ring):
    x, y = points[:, 0:1], points[:, 1:2]
    x1, y1 = ring[:-1, 0], ring[:-1, 1]
    x2, y2 = ring[1:, 0], ring[1:, 1]
    crosses = (y1 > y) != (y2 > y)
    with np.errstate(divide="ignore", invalid="ignore"):
        xint = x1 + (y - y1) * (x2 - x1) / (y2 - y1)
    return ((crosses & (x < xint)).sum(axis=1) % 2) == 1


def _touching(a, b):
    lo, hi = np.maximum(a.min(0), b.min(0)), np.minimum(a.max(0), b.max(0))
    if (lo - hi > NEIGHBOUR_DEG).any():
        return False
    for chunk in np.array_split(a, max(1, len(a) // 2000)):
        d = np.abs(chunk[:, None, :] - b[None, :, :]).max(axis=2)
        if (d < NEIGHBOUR_DEG).any():
            return True
    return False


def _load(path, rename=None):
    rename = rename or {}
    return {
        rename.get(f["properties"]["shapeName"], f["properties"]["shapeName"]): _outer_rings(f["geometry"])
        for f in json.load(open(path))["features"]
    }


def _parent(rings, parents, bbox):
    pts = np.vstack(rings)
    pts = pts + (pts.mean(0) - pts) * 0.05
    lo, hi = pts.min(0), pts.max(0)
    votes = {
        p: sum(_inside(pts, r).sum() for r in prings)
        for p, prings in parents.items()
        if (bbox[p][0] <= hi).all() and (lo <= bbox[p][1]).all()
    }
    return max(votes, key=votes.get)


def _neighbours(shapes):
    verts = {d: np.vstack(rings) for d, rings in shapes.items()}
    out = {d: set() for d in shapes}
    for a, b in combinations(shapes, 2):
        if _touching(verts[a], verts[b]):
            out[a].add(b)
            out[b].add(a)
    return out


def pin_checker(districts_path):
    districts = _load(districts_path)

    def in_district(name, lat, lon):
        # The outlines are simplified, so a pin gets about 5 km of slack in each direction before it counts as outside.
        around = np.array([[lon, lat], [lon + 0.05, lat], [lon - 0.05, lat], [lon, lat + 0.05], [lon, lat - 0.05]])
        return any(_inside(around, ring).any() for ring in districts.get(name, []))

    return in_district


def build_areas(districts_path, upazilas_path, divisions_path):
    districts = _load(districts_path)
    divisions = _load(divisions_path, {"Rajshani": "Rajshahi"})
    district_bbox = {d: (np.vstack(r).min(0), np.vstack(r).max(0)) for d, r in districts.items()}
    division_bbox = {d: (np.vstack(r).min(0), np.vstack(r).max(0)) for d, r in divisions.items()}

    upazila_name, upazila_district = {}, {}
    for f in json.load(open(upazilas_path))["features"]:
        uid = f["properties"]["shapeID"]
        upazila_name[uid] = f["properties"]["shapeName"]
        upazila_district[uid] = _parent(_outer_rings(f["geometry"]), districts, district_bbox)

    return Areas(
        districts=sorted(districts),
        upazila_name=upazila_name,
        upazila_district=upazila_district,
        neighbours=_neighbours(districts),
        centroid={d: tuple(max(rings, key=len).mean(0).round(3)) for d, rings in districts.items()},
        district_division={d: _parent(rings, divisions, division_bbox) for d, rings in districts.items()},
        division_neighbours=_neighbours(divisions),
        division_centroid={d: tuple(max(rings, key=len).mean(0).round(3)) for d, rings in divisions.items()},
    )
