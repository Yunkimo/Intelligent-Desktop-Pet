"""用同一配置和脱敏图片交替测试两版视觉模块，只调用模型，不连接业务库。"""

import argparse
import asyncio
import importlib.util
import json
import statistics
import sys
import time
from collections import Counter
from pathlib import Path

from dotenv import dotenv_values

ROOT = Path(__file__).resolve().parents[1]


def fingerprint(course):
    return (
        course.get("name"),
        course.get("teacher"),
        course.get("day_of_week"),
        course.get("location"),
        tuple(course.get("weeks") or []),
    )


async def measure(module, image, expected):
    started = time.monotonic()
    try:
        result = await asyncio.wait_for(module.parse_schedule_image(image, "image/png"), 300)
        courses = result["courses"] + result.get("pending_courses", [])
        keys = Counter(map(fingerprint, courses))
        match = sum((keys & Counter(map(fingerprint, expected))).values())
        return {
            "seconds": round(time.monotonic() - started, 3),
            "ok": True,
            "rows": len(courses),
            "matched": match,
            "unconfirmed_time_rows": sum(
                c.get("start_time") is None and c.get("end_time") is None for c in courses
            ),
            "rows_for_review": courses,
        }
    except Exception as exc:
        return {
            "seconds": round(time.monotonic() - started, 3),
            "ok": False,
            "error_type": type(exc).__name__,
        }


async def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--baseline-vision", type=Path, required=True)
    parser.add_argument("--env-file", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    sys.path.insert(0, str(ROOT / "backend"))
    from app import config, vision

    settings = dotenv_values(args.env_file)
    for name in ("LLM_API_KEY", "LLM_BASE_URL", "LLM_VISION_MODEL"):
        if not settings.get(name):
            raise SystemExit(f"请在指定配置文件设置 {name}")
        setattr(config, name, settings[name])
    spec = importlib.util.spec_from_file_location("app.b7_baseline", args.baseline_vision)
    baseline = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(baseline)
    folder = ROOT / "tests_fixtures/b7"
    image = (folder / "schedule.png").read_bytes()
    expected = json.loads((folder / "expected.json").read_text(encoding="utf-8"))
    report = {
        "model": config.LLM_VISION_MODEL,
        "expected_rows": len(expected),
        "before": [],
        "after": [],
    }
    for n in range(5):
        for label, module in (("before", baseline), ("after", vision))[:: 1 if n % 2 == 0 else -1]:
            row = await measure(module, image, expected)
            report[label].append(row)
            args.output.write_text(
                json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
            )
            print(label, n + 1, row["ok"], row["seconds"], flush=True)
    summary = {}
    for label in ("before", "after"):
        rows = [r for r in report[label] if r["ok"]]
        elapsed = [r["seconds"] for r in rows]
        summary[label] = {
            "successes": len(rows),
            "median_s": statistics.median(elapsed) if rows else None,
            "max_s": max(r["seconds"] for r in report[label]),
        }
    if all(s["successes"] == 5 for s in summary.values()):
        gain = 1 - summary["after"]["median_s"] / summary["before"]["median_s"]
        summary["median_reduction_percent"] = round(100 * gain, 2)
        summary["latency_target_met"] = gain >= 0.30
    report["summary"] = summary
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(summary))


if __name__ == "__main__":
    asyncio.run(main())
