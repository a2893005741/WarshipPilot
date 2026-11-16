"""Evaluate extracted colors against frames. Never issues device input."""
import json
from pathlib import Path
import time
from typing import Literal

import cv2
import numpy as np
from pydantic import BaseModel, ConfigDict, Field


class ColorProfile(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)
    base_width: int = Field(default=540, ge=16, le=8192)
    base_height: int = Field(default=960, ge=16, le=8192)
    rotation: Literal[0, 90, 180, 270] = 270
    color_order: Literal["RGB", "BGR"] = "BGR"
    tolerance: int = Field(default=20, ge=0, le=80)
    mode: Literal["absolute", "relative"] = "absolute"
    anchor_x: int = Field(default=0, ge=0, le=8191)
    anchor_y: int = Field(default=0, ge=0, le=8191)


class LegacyVision:
    def __init__(self, folder: Path):
        self.folder = folder
        self.catalog = json.loads((folder / "rules.json").read_text(encoding="utf-8"))
        self.items = {item["id"]: item for group in ("point_expressions", "color_groups", "needs_review") for item in self.catalog[group]}
        self.compiled = {}
        for item in self.catalog["point_expressions"]:
            self.compiled[item["id"]] = [
                (p["x"], p["y"], [(self.channels(c["hex"]), self.channels(c["tolerance_hex"] or "000000")) for c in p["colors"]])
                for p in item["points"]]

    @staticmethod
    def channels(value: str):
        return np.array([int(value[i:i+2], 16) for i in (0, 2, 4)], dtype=np.int16)

    def index(self):
        return {"source": self.catalog["source"], "stats": self.catalog["stats"],
                "source_sha256": self.catalog["source_sha256"], "decoded_crc32": self.catalog["decoded_crc32"],
                "items": [{key: item[key] for key in ("id", "kind", "raw", "context_hints")}
                          | {"point_count": item.get("point_count", 0), "contains_negative": item.get("contains_negative", False)}
                          for item in self.items.values()]}

    def detail(self, rule_id):
        if rule_id not in self.items:
            raise ValueError("原脚本规则不存在")
        return self.items[rule_id]

    @staticmethod
    def decode(raw):
        image = cv2.imdecode(np.frombuffer(raw, np.uint8), cv2.IMREAD_COLOR)
        if image is None or max(image.shape[:2]) > 8192:
            raise ValueError("无效图片或图片尺寸超过8192像素")
        return cv2.cvtColor(image, cv2.COLOR_BGR2RGB)

    @staticmethod
    def mapping(profile, width, height):
        bw, bh = profile.base_width, profile.base_height
        tw, th = (bh, bw) if profile.rotation in (90, 270) else (bw, bh)
        if abs((width / height) / (tw / th) - 1) > 0.02:
            raise ValueError(f"画面{width}×{height}与当前设置旋转后的{tw}×{th}比例不符，请调整原坐标尺寸和旋转")
        sx, sy = (width - 1) / (tw - 1), (height - 1) / (th - 1)

        def transform(x, y):
            relative = profile.mode == "relative"
            if profile.rotation == 90:
                x, y = (-y if relative else bh - 1 - y), x
            elif profile.rotation == 180:
                x, y = (-x if relative else bw - 1 - x), (-y if relative else bh - 1 - y)
            elif profile.rotation == 270:
                x, y = y, (-x if relative else bw - 1 - x)
            x, y = round(x * sx), round(y * sy)
            if relative:
                x += profile.anchor_x
                y += profile.anchor_y
            return x, y

        return transform

    def evaluate(self, image, rule_id, profile, details=True):
        item = self.detail(rule_id)
        if item["kind"] != "points":
            return {"id": rule_id, "status": "unavailable", "reason": "此项只有颜色或语法待核对，缺少可直接核对的坐标", "matched": False}
        height, width = image.shape[:2]
        transform = self.mapping(profile, width, height)
        rows = []
        matched_count, outside, total_delta = 0, 0, 0.0
        for index, (source_x, source_y, colors) in enumerate(self.compiled[rule_id]):
            x, y = transform(source_x, source_y)
            valid_source = profile.mode == "relative" or (0 <= source_x < profile.base_width and 0 <= source_y < profile.base_height)
            valid = valid_source and 0 <= x < width and 0 <= y < height
            row = {"index": index, "source_x": source_x, "source_y": source_y, "x": x, "y": y, "in_bounds": valid}
            if valid:
                actual = image[y, x].astype(np.int16)
                alternatives = []
                for expected, embedded_tolerance in colors:
                    if profile.color_order == "BGR":
                        expected, embedded_tolerance = expected[::-1], embedded_tolerance[::-1]
                    tolerance = np.maximum(embedded_tolerance, profile.tolerance)
                    delta = np.abs(actual - expected)
                    alternatives.append((bool(np.all(delta <= tolerance)), float(np.mean(delta)), expected, tolerance, delta))
                best = min(alternatives, key=lambda a: (not a[0], a[1]))
                matched_count += best[0]
                total_delta += best[1]
                row.update(matched=best[0], actual_rgb="".join(f"{c:02X}" for c in actual),
                           expected_rgb="".join(f"{c:02X}" for c in best[2]), tolerance=best[3].tolist(), delta=best[4].tolist())
            else:
                outside += 1
                total_delta += 255
                row.update(matched=False, actual_rgb=None, expected_rgb=None, reason="原坐标或变换后的点超出范围")
            if details:
                rows.append(row)
        total = len(self.compiled[rule_id])
        return {"id": rule_id, "status": "out_of_bounds" if outside else "evaluated", "matched": matched_count == total and not outside,
                "matched_points": matched_count, "total_points": total, "outside_points": outside,
                "match_rate": round(matched_count / total, 4), "mean_delta": round(total_delta / total, 2),
                "points": rows, "context_hints": item["context_hints"], "profile": profile.model_dump(),
                "width": width, "height": height}

    def scan(self, image, profile):
        start = time.monotonic()
        self.mapping(profile, image.shape[1], image.shape[0])
        ranked, excluded = [], 0
        for rule_id, item in self.items.items():
            # Single points and pairs are too weak to rank as page candidates.
            if item["kind"] != "points" or item["point_count"] < 3:
                continue
            result = self.evaluate(image, rule_id, profile, details=False)
            if result["outside_points"]:
                excluded += 1
                continue
            ranked.append(result)
        ranked.sort(key=lambda r: (not r["matched"], -r["match_rate"], r["mean_delta"], -r["total_points"]))
        return {"candidates": ranked[:12], "evaluated_rules": len(ranked), "excluded_rules": excluded,
                "fully_matched": sum(r["matched"] for r in ranked), "latency_ms": round((time.monotonic() - start) * 1000),
                "profile": profile.model_dump(), "candidate_only": True}
