import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from training.adaptive_builder import (
    _design_structure_counts,
    _design_structure_guidance,
    _reference_volume_structure_context,
)


class DesignVolumeContextTests(unittest.TestCase):
    def test_builds_bounded_context_from_each_volume_outline(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            outlines = Path(temp_dir)
            for number in range(1, 4):
                volume = outlines / f"vol_{number:02d}_卷{number}"
                volume.mkdir()
                (volume / "meta.json").write_text(
                    json.dumps({"start_ch": number * 10 - 9, "end_ch": number * 10}),
                    encoding="utf-8",
                )
                (volume / "volume_outline.md").write_text(
                    "# 一、卷纲概览\n"
                    + f"第{number}卷核心矛盾与地图变化。\n"
                    + "概览内容" * 700
                    + "\n# 二、三幕结构\n"
                    + f"第{number}卷三幕推进。\n"
                    + "三幕内容" * 700
                    + "\n# 人物谱系\n不应优先进入摘要。\n"
                    + "\n# 伏笔追踪\n"
                    + f"第{number}卷跨卷钩子。\n"
                    + "伏笔内容" * 700,
                    encoding="utf-8",
                )

            context = _reference_volume_structure_context(
                SimpleNamespace(reference_outlines=str(outlines)),
                per_volume_chars=3200,
                max_chars=12000,
            )

            self.assertEqual(context.count("## 参考卷"), 3)
            self.assertIn("## 参考卷1：卷1｜第1-10章", context)
            self.assertIn("第3卷三幕推进", context)
            self.assertNotIn("第2卷跨卷钩子", context)
            self.assertNotIn("不应优先进入摘要", context)
            self.assertLessEqual(len(context), 12000)

    def test_stage_count_matches_reference_volume_count(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            outlines = Path(temp_dir)
            for number in range(1, 14):
                (outlines / f"vol_{number:02d}_卷{number}").mkdir()
            guidance = _design_structure_guidance(
                SimpleNamespace(reference_outlines=str(outlines))
            )
            self.assertEqual(guidance["reference_volume_count"], 13)
            self.assertEqual(guidance["stage_range"], "13")
            self.assertEqual(guidance["stage_min"], 13)
            self.assertEqual(guidance["stage_max"], 13)
            self.assertEqual(guidance["map_range"], "10-13")

    def test_counts_stage_and_map_structure(self):
        rough = "\n".join(f"## 阶段{number}：测试" for number in range(1, 9))
        worldview = (
            "# 6. 地图/舞台层级\n"
            + "\n".join(f"- 地图{number}：测试" for number in range(1, 7))
            + "\n# 7. 主要矛盾\n内容"
        )
        self.assertEqual(_design_structure_counts(rough, worldview), (8, 6))

    def test_counts_common_heading_variants(self):
        rough = "\n".join([
            "# 阶段粗纲",
            "### 第一阶段：起步",
            "### 第二阶段：扩张",
            "### 阶段三：转折",
            "4. 阶段四：远行",
            "5. 第五阶段：战争",
            "6. 阶段6：真相",
            "7. 阶段七：反攻",
            "8. 第八阶段：终局",
        ])
        worldview = "\n".join([
            "## 6. 地图与舞台层级",
            "1. 起始城市",
            "2. 边境荒原",
            "3. 王国腹地",
            "4. 海外群岛",
            "5. 天空领域",
            "6. 世界核心",
            "## 7. 主要矛盾",
            "内容",
        ])
        self.assertEqual(_design_structure_counts(rough, worldview), (8, 6))

    def test_counts_verbose_map_heading_and_named_levels(self):
        rough = "\n".join(f"## 阶段{number}：测试" for number in range(1, 9))
        worldview = "\n".join([
            "## 6、地图与舞台层级（由低到高）",
            "层级一：矿区",
            "层级二：工业城",
            "层级三：王都",
            "层级四：海外",
            "层级五：天空",
            "层级六：世界核心",
            "## 7、主要矛盾",
            "内容",
        ])
        self.assertEqual(_design_structure_counts(rough, worldview), (8, 6))


if __name__ == "__main__":
    unittest.main()
