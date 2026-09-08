"""内容文件继承（extends / [keep]）的测试。

按岗位做定制版时，整份抄一遍的代价是以后改手机号要记得改五处。所以内容文件
可以像 theme.en.toml 继承 theme.toml 那样，只写要改的地方。

这里盯的是几件"错了但看不出来"的事：
  · 定制版没写的字段真的继承下来了（漏继承 → PDF 上少一段，投出去才发现）
  · [keep] 里名字拼错必须当场报错，不能静默丢掉一条经历
  · 继承成环要报错，不能无限递归
  · fill.py 和网页版都不许把定制版整份重写（会抹掉 extends）
"""

from __future__ import annotations

import subprocess
import sys
import tempfile
import tomllib
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import render                                                # noqa: E402
import schema                                                # noqa: E402

BASE = (ROOT / "content.example.toml").read_text(encoding="utf-8")


class VariantTestCase(unittest.TestCase):
    """每个用例在自己的临时目录里搭一套内容文件，不碰仓库里的真实文件。"""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)
        self.base = self.dir / "content.toml"
        self.base.write_text(BASE, encoding="utf-8")

    def tearDown(self):
        self.tmp.cleanup()

    def variant(self, body: str, name: str = "content.acme.toml") -> Path:
        path = self.dir / name
        path.write_text(f'extends = "content.toml"\n{body}', encoding="utf-8")
        return path


class InheritTest(VariantTestCase):
    def test_unwritten_fields_are_inherited(self):
        merged = render.load_content(self.variant('[profile]\nintent = "新意向"\n'))
        original = tomllib.loads(BASE)
        self.assertEqual(merged["profile"]["intent"], "新意向")
        self.assertEqual(merged["profile"]["name"], original["profile"]["name"])
        self.assertEqual(len(merged["contacts"]), len(original["contacts"]))
        self.assertEqual(len(merged["experiences"]), len(original["experiences"]))
        self.assertEqual(merged["education"], original["education"])

    def test_merged_variant_has_no_blanks(self):
        merged = render.load_content(self.variant('[profile]\nintent = "新意向"\n'))
        self.assertEqual(schema.find_blanks(merged), [])

    def test_tables_merge_key_by_key(self):
        merged = render.load_content(self.variant(
            '[document]\noutput_basename = "定制"\n'
        ))
        self.assertEqual(merged["document"]["output_basename"], "定制")
        # 同一张表里没写的键要留着
        self.assertEqual(merged["document"]["title"], tomllib.loads(BASE)["document"]["title"])

    def test_array_tables_are_replaced_wholesale(self):
        merged = render.load_content(self.variant(
            '[[skills]]\nlabel = "只此一条"\ntext = "定制版自己写的"\n'
        ))
        self.assertEqual(len(merged["skills"]), 1)
        self.assertEqual(merged["skills"][0]["label"], "只此一条")

    def test_extends_and_keep_are_stripped_from_the_result(self):
        merged = render.load_content(self.variant('[keep]\nskills = ["SEO 执行"]\n'))
        self.assertNotIn("extends", merged)
        self.assertNotIn("keep", merged)

    def test_inheritance_can_be_two_deep(self):
        mid = self.dir / "content.mid.toml"
        mid.write_text('extends = "content.toml"\n[profile]\nintent = "中层"\n',
                       encoding="utf-8")
        leaf = self.dir / "content.leaf.toml"
        leaf.write_text('extends = "content.mid.toml"\n[summary]\ntext = "叶子"\n',
                        encoding="utf-8")
        merged = render.load_content(leaf)
        self.assertEqual(merged["summary"]["text"], "叶子")
        self.assertEqual(merged["profile"]["intent"], "中层")     # 来自中层
        self.assertEqual(merged["profile"]["name"], "张三")        # 来自基底

    def test_missing_parent_is_reported(self):
        path = self.dir / "content.orphan.toml"
        path.write_text('extends = "content.nope.toml"\n', encoding="utf-8")
        with self.assertRaises(ValueError) as caught:
            render.load_content(path)
        self.assertIn("不存在", str(caught.exception))

    def test_cycles_are_refused(self):
        one = self.dir / "content.one.toml"
        two = self.dir / "content.two.toml"
        one.write_text('extends = "content.two.toml"\n', encoding="utf-8")
        two.write_text('extends = "content.one.toml"\n', encoding="utf-8")
        with self.assertRaises(ValueError) as caught:
            render.load_content(one)
        self.assertIn("成环", str(caught.exception))

    def test_a_plain_file_still_loads(self):
        merged = render.load_content(self.base)
        self.assertEqual(schema.find_blanks(merged), [])


class KeepTest(VariantTestCase):
    def test_picks_and_reorders_by_identity(self):
        merged = render.load_content(self.variant(
            '[keep]\nskills = ["数据分析", "SEO 执行"]\n'
        ))
        self.assertEqual([s["label"] for s in merged["skills"]],
                         ["数据分析", "SEO 执行"])

    def test_works_on_every_repeat_block(self):
        # 联系方式那一条从示例内容里读出来，不写死。
        # 示例里的联系方式是模板作者的个人域名和 GitHub，属于 .identifiers 只允许
        # 出现在 content.example.toml 里的标识串——抄进这个文件会被 make check 拦下。
        contact = tomllib.loads(BASE)["contacts"][-1]["value"]
        merged = render.load_content(self.variant(
            '[keep]\n'
            'experiences = ["Globex 软件"]\n'
            'projects = ["Site Monitor"]\n'
            f'contacts = ["{contact}"]\n'
        ))
        self.assertEqual([e["company"] for e in merged["experiences"]], ["Globex 软件"])
        self.assertEqual([p["title"] for p in merged["projects"]], ["Site Monitor"])
        self.assertEqual(len(merged["contacts"]), 1)

    def test_a_typo_fails_loudly_and_lists_the_options(self):
        with self.assertRaises(ValueError) as caught:
            render.load_content(self.variant('[keep]\nskills = ["数据分晰"]\n'))
        message = str(caught.exception)
        self.assertIn("数据分晰", message)
        self.assertIn("数据分析", message)       # 把可选值列出来

    def test_a_block_that_cannot_be_picked_is_refused(self):
        with self.assertRaises(ValueError) as caught:
            render.load_content(self.variant('[keep]\neducation = ["示例大学"]\n'))
        self.assertIn("education", str(caught.exception))

    def test_keep_must_be_a_list(self):
        with self.assertRaises(ValueError):
            render.load_content(self.variant('[keep]\nskills = "SEO 执行"\n'))

    def test_keep_without_extends_is_refused(self):
        path = self.dir / "content.solo.toml"
        path.write_text('[keep]\nskills = ["SEO 执行"]\n', encoding="utf-8")
        with self.assertRaises(ValueError) as caught:
            render.load_content(path)
        self.assertIn("extends", str(caught.exception))

    def test_variant_arrays_win_over_keep(self):
        """同时写了 [keep] 和 [[skills]]：数组表整块替换，keep 的结果被盖掉。"""
        merged = render.load_content(self.variant(
            '[keep]\nskills = ["数据分析"]\n'
            '[[skills]]\nlabel = "自己写的"\ntext = "整块替换"\n'
        ))
        self.assertEqual([s["label"] for s in merged["skills"]], ["自己写的"])


class IdentityTest(unittest.TestCase):
    def test_every_repeat_block_has_a_usable_identity(self):
        for block in schema.BLOCKS:
            if not block.repeat:
                continue
            with self.subTest(block=block.key):
                self.assertTrue(block.identity, f"{block.key} 缺 identity")
                keys = [f.key for f in block.fields]
                self.assertIn(block.identity, keys)

    def test_identity_fields_are_required_so_they_always_exist(self):
        # identity 用来认条目。如果它可以留空，[keep] 就会认到一堆空字符串上。
        for block in schema.BLOCKS:
            if not (block.repeat and block.identity):
                continue
            field = next(f for f in block.fields if f.key == block.identity)
            with self.subTest(block=block.key):
                self.assertTrue(field.required, f"{block.key}.{block.identity} 应是必填")

    def test_example_content_has_unique_identities(self):
        content = tomllib.loads(BASE)
        for block in schema.BLOCKS:
            if not (block.repeat and block.identity):
                continue
            values = [row[block.identity] for row in content[block.key]]
            with self.subTest(block=block.key):
                self.assertEqual(len(values), len(set(values)),
                                 f"{block.key} 的 {block.identity} 有重复，[keep] 会认错")


class RefuseRewriteTest(VariantTestCase):
    """定制版不许被整份重写——那会把 extends 和 [keep] 抹掉，且不报错。"""

    def test_fill_refuses_to_edit_a_variant(self):
        path = self.variant('[profile]\nintent = "新意向"\n')
        result = subprocess.run(
            [sys.executable, str(ROOT / "fill.py"), "--out", str(path)],
            capture_output=True, text=True, input="", timeout=60,
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("定制版", result.stdout + result.stderr)

    def test_fill_check_looks_at_the_merged_result(self):
        path = self.variant('[profile]\nintent = "新意向"\n')
        result = subprocess.run(
            [sys.executable, str(ROOT / "fill.py"), "--check", "--out", str(path)],
            capture_output=True, text=True, timeout=60,
        )
        # 合并之后没有空白，所以应当通过——而不是把定制版那十几行当成一份残缺内容
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_render_accepts_a_variant_end_to_end(self):
        path = self.variant('[document]\noutput_basename = "变体"\n')
        out = self.dir / "build"
        result = subprocess.run(
            [sys.executable, str(ROOT / "render.py"),
             "--content", str(path), "--out-dir", str(out)],
            capture_output=True, text=True, timeout=180,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertTrue((out / "变体.pdf").exists())


if __name__ == "__main__":
    unittest.main(verbosity=2)
