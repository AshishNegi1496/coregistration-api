from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from api.utils import ensure_dir


def _translate_to_cog(source: Path, destination: Path) -> None:
    try:
        from osgeo import gdal
    except Exception as exc:
        raise RuntimeError(f"GDAL is required for COG export: {exc}") from exc

    ensure_dir(destination.parent)

    dataset = gdal.Open(str(source))
    if dataset is None:
        raise RuntimeError(f"Could not open coregistered raster: {source}")

    if gdal.GetDriverByName("COG") is not None:
        gdal.Translate(
            str(destination),
            dataset,
            format="COG",
            creationOptions=[
                "COMPRESS=LZW",
                "BLOCKSIZE=512",
            ],
        )
        return

    gdal.Translate(
        str(destination),
        dataset,
        format="GTiff",
        creationOptions=[
            "COMPRESS=LZW",
            "TILED=YES",
            "BLOCKXSIZE=512",
            "BLOCKYSIZE=512",
        ],
    )


def _get_image_info(path: Path) -> dict:
    from osgeo import gdal

    ds = gdal.Open(str(path))

    if ds is None:
        raise RuntimeError(f"Could not open image: {path}")

    gt = ds.GetGeoTransform()

    return {
        "width": ds.RasterXSize,
        "height": ds.RasterYSize,
        "bands": ds.RasterCount,
        "pixel_size": abs(gt[1]),
    }


def _choose_coreg_params(ref: Path, tgt: Path) -> dict:
    ref_info = _get_image_info(ref)
    tgt_info = _get_image_info(tgt)

    ref_gsd = ref_info["pixel_size"]
    tgt_gsd = tgt_info["pixel_size"]

    ratio = max(ref_gsd, tgt_gsd) / min(ref_gsd, tgt_gsd)

    params = {
        "grid_res": 2048,
        "window_size": (256, 256),
        "max_shift": 100,
        "min_reliability": 40,
    }

    if ratio < 2:
        params.update(
            {
                "grid_res": 1024,
                "window_size": (256, 256),
                "max_shift": 50,
            }
        )

    elif ratio < 5:
        params.update(
            {
                "grid_res": 2048,
                "window_size": (512, 512),
                "max_shift": 200,
            }
        )

    else:
        params.update(
            {
                "grid_res": 4096,
                "window_size": (1024, 1024),
                "max_shift": 500,
            }
        )

    return params


def _run_arosics_coregistration(
    ref: Path,
    tgt: Path,
    out_img: Path,
) -> dict[str, object]:

    try:
        from arosics import COREG_LOCAL
    except Exception as exc:
        raise RuntimeError(
            f"AROSICS is required for local coregistration: {exc}"
        ) from exc

    ensure_dir(out_img.parent)

    params = _choose_coreg_params(ref, tgt)

    print(f"\nAdaptive parameters selected:")
    print(json.dumps(params, indent=2))

    attempts = [
        {
            "grid_res": params["grid_res"],
            "window_size": params["window_size"],
            "min_reliability": 60,
        },
        {
            "grid_res": max(params["grid_res"], 2048),
            "window_size": (512, 512),
            "min_reliability": 40,
        },
        {
            "grid_res": max(params["grid_res"], 4096),
            "window_size": (1024, 1024),
            "min_reliability": 20,
        },
    ]

    coreg = None
    last_error = None

    matched_points = 0
    valid_points = 0

    for idx, attempt in enumerate(attempts, start=1):

        print(
            f"\nCoreg attempt {idx}: "
            f"grid={attempt['grid_res']} "
            f"window={attempt['window_size']} "
            f"reliability={attempt['min_reliability']}"
        )

        try:

            coreg = COREG_LOCAL(
                im_ref=str(ref),
                im_tgt=str(tgt),
                grid_res=attempt["grid_res"],
                window_size=attempt["window_size"],
                max_shift=params["max_shift"],
                tieP_filter_level=3,
                min_reliability=attempt["min_reliability"],
                rs_max_outlier=10,
                CPUs=12,
                fmt_out="GTiff",
                path_out=str(out_img),
                resamp_alg_calc="nearest",
                resamp_alg_deshift="nearest",
                match_gsd=True,
                q=False,
            )

            coreg.calculate_spatial_shifts()

            table = getattr(coreg, "CoRegPoints_table", None)

            matched_points = 0
            valid_points = 0

            if table is not None:

                matched_points = len(table)

                valid = table[
                    (table["ABS_SHIFT"] != -9999)
                    & (table["OUTLIER"] == 0)
                ]

                valid_points = len(valid)

            print(
                f"Attempt {idx}: "
                f"matched={matched_points}, "
                f"valid={valid_points}"
            )

            if valid_points >= 5:
                print("Accepted result.")
                break

            coreg = None

        except Exception as exc:
            print(f"Attempt {idx} failed: {exc}")
            last_error = exc
            coreg = None

    if coreg is None:
        raise RuntimeError(
            f"All coregistration attempts failed. Last error: {last_error}"
        )

    coreg.correct_shifts()

    if not out_img.exists():
        raise RuntimeError(
            f"AROSICS completed but output not generated: {out_img}"
        )

    quality = "failed"

    if valid_points > 50:
        quality = "excellent"
    elif valid_points > 20:
        quality = "good"
    elif valid_points > 5:
        quality = "usable"

    return {
        "coreg_output": str(out_img.resolve()),
        "matched_points": matched_points,
        "valid_points": valid_points,
        "quality": quality,
        "parameters": params,
    }


def run_coregistration_and_cog(
    ref: Path,
    tgt: Path,
    run_dir: Path,
) -> dict[str, str]:

    ensure_dir(run_dir)

    coreg_dir = ensure_dir(run_dir / "coreg")
    cog_dir = ensure_dir(run_dir / "cog")
    report_dir = ensure_dir(run_dir / "reports")

    coreg_output = coreg_dir / f"{tgt.stem}_coregistered.tif"
    cog_output = cog_dir / f"{tgt.stem}_cog.tif"

    summary = _run_arosics_coregistration(
        ref,
        tgt,
        coreg_output,
    )

    if not coreg_output.exists():
        raise RuntimeError(
            f"Coregistration output not generated: {coreg_output}"
        )

    _translate_to_cog(coreg_output, cog_output)

    report_path = report_dir / f"{tgt.stem}_coreg_report.json"

    report_path.write_text(
        json.dumps(
            {
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "reference": str(ref),
                "target": str(tgt),
                "coreg_output": str(coreg_output.resolve()),
                "cog_output": str(cog_output.resolve()),
                "matched_points": summary.get("matched_points", 0),
                "valid_points": summary.get("valid_points", 0),
                "quality": summary.get("quality"),
                "parameters": summary.get("parameters"),
            },
            indent=2,
        ),
        encoding="utf-8",
    )

    summary.update(
        {
            "cog_output": str(cog_output.resolve()),
            "report": str(report_path.resolve()),
        }
    )

    return summary