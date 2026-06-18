from __future__ import annotations

import re
from pathlib import Path
from sqlalchemy.orm import Session


IMAGE_EXTENSIONS = {".tif", ".tiff", ".jp2"}
SENSOR_ALIASES = {
    "sentinel-2": {"sentinel-2", "sentinel2", "s2"},
    "cartosat": {"cartosat", "c2"},
    "landsat-8": {"landsat-8", "landsat8", "l8"},
}


def ensure_dir(path: Path) -> Path:
    path.mkdir(parents=True, exist_ok=True)
    return path


def resolve_input_path(root: Path, value: str) -> Path:
    candidate = Path(value).expanduser()
    if not candidate.is_absolute():
        candidate = root / candidate
    resolved = candidate.resolve()
    root_resolved = root.resolve()
    if resolved != root_resolved and root_resolved not in resolved.parents:
        raise ValueError(f"Path must stay inside {root_resolved}")
    return resolved


def find_first_image(root: Path) -> Path | None:
    if not root.exists():
        return None
    for path in sorted(root.rglob("*")):
        if path.is_file() and path.suffix.lower() in IMAGE_EXTENSIONS:
            return path.resolve()
    return None


def list_image_files(root: Path, recursive: bool = True) -> list[Path]:
    if not root.exists():
        return []
    iterator = root.rglob("*") if recursive else root.iterdir()
    files: list[Path] = []
    for path in iterator:
        if path.is_file() and path.suffix.lower() in IMAGE_EXTENSIONS:
            files.append(path.resolve())
    return sorted(files)


def normalize_text(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", value.lower()).strip()


def infer_sensor_label(value: str | None) -> str | None:
    if not value:
        return None
    normalized = normalize_text(value)
    compact = normalized.replace(" ", "")
    for canonical, aliases in SENSOR_ALIASES.items():
        if canonical.replace("-", "") in compact:
            return canonical
        for alias in aliases:
            if alias.replace("-", "") in compact:
                return canonical
    return None


def path_tokens(path: Path) -> list[str]:
    text = normalize_text(path.stem + " " + str(path.parent))
    return [token for token in text.split() if token]


def shared_token_count(left: Path, right: Path) -> int:
    left_tokens = set(path_tokens(left))
    right_tokens = set(path_tokens(right))
    return len(left_tokens & right_tokens)


def extract_resolution_score(path: Path) -> float | None:
    text = f"{path.name} {path.parent}".lower()
    match = re.search(r"(?<!\d)(\d+(?:\.\d+)?)\s*m(?![a-z])", text)
    if not match:
        return None
    return float(match.group(1))


def gdal_pixel_size(path: Path) -> float | None:
    try:
        from osgeo import gdal
    except Exception:
        return None

    ds = gdal.Open(str(path))
    if ds is None:
        return None

    gt = ds.GetGeoTransform()
    if not gt:
        return None
    return max(abs(gt[1]), abs(gt[5]))


def _spatial_reference_from_wkt(wkt: str | None):
    if not wkt:
        return None

    try:
        from osgeo import osr
    except Exception:
        return None

    srs = osr.SpatialReference()
    if srs.ImportFromWkt(wkt) != 0:
        return None
    try:
        srs.AutoIdentifyEPSG()
    except Exception:
        pass
    return srs


def _spatial_reference_from_epsg(epsg: int):
    try:
        from osgeo import osr
    except Exception:
        return None

    srs = osr.SpatialReference()
    if srs.ImportFromEPSG(epsg) != 0:
        return None
    return srs


def _bounds_from_dataset(ds) -> dict[str, float] | None:
    gt = ds.GetGeoTransform()
    if not gt:
        return None

    cols = ds.RasterXSize
    rows = ds.RasterYSize
    corners = (
        (0, 0),
        (cols, 0),
        (cols, rows),
        (0, rows),
    )
    xs = [gt[0] + col * gt[1] + row * gt[2] for col, row in corners]
    ys = [gt[3] + col * gt[4] + row * gt[5] for col, row in corners]
    return {
        "min_x": min(xs),
        "min_y": min(ys),
        "max_x": max(xs),
        "max_y": max(ys),
    }


def _bounds_area(bounds: dict[str, float] | None) -> float:
    if not bounds:
        return 0.0
    width = max(0.0, bounds["max_x"] - bounds["min_x"])
    height = max(0.0, bounds["max_y"] - bounds["min_y"])
    return width * height


def _bounds_intersection(
    left: dict[str, float] | None,
    right: dict[str, float] | None,
) -> dict[str, float] | None:
    if not left or not right:
        return None

    intersection = {
        "min_x": max(left["min_x"], right["min_x"]),
        "min_y": max(left["min_y"], right["min_y"]),
        "max_x": min(left["max_x"], right["max_x"]),
        "max_y": min(left["max_y"], right["max_y"]),
    }
    if intersection["max_x"] <= intersection["min_x"] or intersection["max_y"] <= intersection["min_y"]:
        return None
    return intersection


def _transform_bounds(
    bounds: dict[str, float] | None,
    source_wkt: str | None,
    target_wkt: str | None,
) -> dict[str, float] | None:
    if not bounds or not source_wkt or not target_wkt:
        return None

    try:
        from osgeo import osr
    except Exception:
        return None

    source_srs = _spatial_reference_from_wkt(source_wkt)
    target_srs = _spatial_reference_from_wkt(target_wkt)
    if source_srs is None or target_srs is None:
        return None

    try:
        transform = osr.CoordinateTransformation(source_srs, target_srs)
    except Exception:
        return None

    corners = (
        (bounds["min_x"], bounds["min_y"]),
        (bounds["min_x"], bounds["max_y"]),
        (bounds["max_x"], bounds["min_y"]),
        (bounds["max_x"], bounds["max_y"]),
    )
    xs: list[float] = []
    ys: list[float] = []
    for x, y in corners:
        try:
            tx, ty, *_ = transform.TransformPoint(x, y)
        except Exception:
            return None
        xs.append(float(tx))
        ys.append(float(ty))

    return {
        "min_x": min(xs),
        "min_y": min(ys),
        "max_x": max(xs),
        "max_y": max(ys),
    }


def raster_geo_metadata(path: Path) -> dict[str, object] | None:
    try:
        from osgeo import gdal
    except Exception:
        return None

    ds = gdal.Open(str(path))
    if ds is None:
        return None

    bounds_native = _bounds_from_dataset(ds)
    projection = ds.GetProjection() or None
    srs = _spatial_reference_from_wkt(projection)
    wgs84_srs = _spatial_reference_from_epsg(4326) if srs is not None else None
    bounds_wgs84 = _transform_bounds(
        bounds_native,
        projection,
        wgs84_srs.ExportToWkt() if wgs84_srs is not None else None,
    )

    crs_label = None
    if srs is not None:
        auth_name = srs.GetAuthorityName(None)
        auth_code = srs.GetAuthorityCode(None)
        if auth_name and auth_code:
            crs_label = f"{auth_name}:{auth_code}"
        else:
            crs_label = srs.GetName() or None

    return {
        "path": path,
        "projection": projection,
        "crs_label": crs_label,
        "bounds_native": bounds_native,
        "bounds_wgs84": bounds_wgs84,
        "pixel_size": gdal_pixel_size(path),
    }


def geo_overlap_metrics(target_path: Path, candidate_path: Path) -> dict[str, object] | None:
    target = raster_geo_metadata(target_path)
    candidate = raster_geo_metadata(candidate_path)
    if target is None or candidate is None:
        return None

    target_proj = target["projection"]
    candidate_proj = candidate["projection"]
    target_bounds_native = target["bounds_native"]
    candidate_bounds_native = candidate["bounds_native"]

    common_target_bounds = target_bounds_native
    common_candidate_bounds = candidate_bounds_native
    common_crs = target_proj

    if target_proj and candidate_proj and target_proj != candidate_proj:
        common_candidate_bounds = _transform_bounds(candidate_bounds_native, candidate_proj, target_proj)
    if common_candidate_bounds is None and target["bounds_wgs84"] and candidate["bounds_wgs84"]:
        common_target_bounds = target["bounds_wgs84"]
        common_candidate_bounds = candidate["bounds_wgs84"]
        common_crs = "EPSG:4326"

    intersection = _bounds_intersection(common_target_bounds, common_candidate_bounds)
    target_area = _bounds_area(common_target_bounds)
    candidate_area = _bounds_area(common_candidate_bounds)
    intersection_area = _bounds_area(intersection)
    union_area = max(0.0, target_area + candidate_area - intersection_area)

    bbox_overlap_pct = (intersection_area / target_area * 100.0) if target_area else 0.0
    candidate_overlap_pct = (intersection_area / candidate_area * 100.0) if candidate_area else 0.0
    union_overlap_pct = (intersection_area / union_area * 100.0) if union_area else 0.0
    geometry_overlap_pct = min(bbox_overlap_pct, candidate_overlap_pct)

    target_wgs84 = target["bounds_wgs84"]
    candidate_wgs84 = candidate["bounds_wgs84"]
    latlon_intersection = _bounds_intersection(target_wgs84, candidate_wgs84)
    latlon_target_area = _bounds_area(target_wgs84)
    latlon_intersection_area = _bounds_area(latlon_intersection)
    latlon_overlap_pct = (latlon_intersection_area / latlon_target_area * 100.0) if latlon_target_area else 0.0

    source_srs = _spatial_reference_from_wkt(target_proj) if target_proj else None
    candidate_srs = _spatial_reference_from_wkt(candidate_proj) if candidate_proj else None
    crs_match = bool(source_srs and candidate_srs and source_srs.IsSame(candidate_srs))

    return {
        "same_crs": crs_match,
        "target_crs": target["crs_label"],
        "candidate_crs": candidate["crs_label"],
        "common_crs": common_crs,
        "target_bounds": common_target_bounds,
        "candidate_bounds": common_candidate_bounds,
        "intersection_bounds": intersection,
        "target_area": target_area,
        "candidate_area": candidate_area,
        "intersection_area": intersection_area,
        "bbox_overlap_pct": round(bbox_overlap_pct, 3),
        "candidate_overlap_pct": round(candidate_overlap_pct, 3),
        "extent_intersection_pct": round(union_overlap_pct, 3),
        "geometry_overlap_pct": round(geometry_overlap_pct, 3),
        "latlon_overlap_pct": round(latlon_overlap_pct, 3),
        "target_wgs84": target_wgs84,
        "candidate_wgs84": candidate_wgs84,
    }


def best_candidate(paths: list[Path]) -> Path | None:
    if not paths:
        return None

    def sort_key(path: Path) -> tuple[float, int, str]:
        score = gdal_pixel_size(path)
        if score is None:
            score = extract_resolution_score(path)
        size_rank = -path.stat().st_size if path.exists() else 0
        return (score if score is not None else float("inf"), size_rank, path.name.lower())

    return sorted(paths, key=sort_key)[0]


# ============================================================
# DUPLICATE DETECTION HELPER
# ============================================================

def is_file_already_processed(
    db: Session,
    file_path: Path,
) -> bool:
    """
    Check if a file has already been processed as a target image.
    
    Used by both auto-scan and manual upload flows to prevent duplicate
    coregistration jobs.
    
    Args:
        db: SQLAlchemy session
        file_path: Path to the TIFF file (will be normalized)
    
    Returns:
        True if CoregJob with matching target_image exists, False otherwise
    """
    from api.models import CoregJob
    
    # Normalize path for comparison
    normalized_path = str(file_path.resolve())
    
    # Query for any job with this target_image
    existing_job = db.query(CoregJob).filter(
        CoregJob.target_image == normalized_path
    ).first()
    
    return existing_job is not None
