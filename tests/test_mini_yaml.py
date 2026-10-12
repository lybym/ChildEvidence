import unittest

from research_library.mini_yaml import parse, YAMLError


class MiniYamlTest(unittest.TestCase):
    def test_scalars(self):
        text = """
int_val: 42
float_val: 1.5
bool_true: true
bool_false: false
null_val: null
quoted: "hello: world"
plain: hello world
"""
        v = parse(text)
        self.assertEqual(v["int_val"], 42)
        self.assertEqual(v["float_val"], 1.5)
        self.assertTrue(v["bool_true"])
        self.assertFalse(v["bool_false"])
        self.assertIsNone(v["null_val"])
        self.assertEqual(v["quoted"], "hello: world")
        self.assertEqual(v["plain"], "hello world")

    def test_nested_map_and_inline_list(self):
        text = """
domains:
  child_development:
    quota: 26
    queries:
      - id: q1
        tags: [executive_function, cognitive_control]
        openalex:
          filter:
            title.search: executive function
            type: article|review
          sort: cited_by_count:desc
        limit: 6
"""
        v = parse(text)
        q = v["domains"]["child_development"]["queries"][0]
        self.assertEqual(q["id"], "q1")
        self.assertEqual(q["tags"], ["executive_function", "cognitive_control"])
        self.assertEqual(q["openalex"]["filter"]["title.search"], "executive function")
        self.assertEqual(q["openalex"]["filter"]["type"], "article|review")
        self.assertEqual(q["openalex"]["sort"], "cited_by_count:desc")
        self.assertEqual(q["limit"], 6)
        self.assertEqual(v["domains"]["child_development"]["quota"], 26)

    def test_list_of_scalars_block_style(self):
        text = """
allowed:
  - europepmc
  - openalex
  - eric
"""
        v = parse(text)
        self.assertEqual(v["allowed"], ["europepmc", "openalex", "eric"])

    def test_comments_ignored(self):
        text = """
# a comment
key: value  # not an inline comment - kept verbatim
"""
        v = parse(text)
        self.assertEqual(v["key"], "value  # not an inline comment - kept verbatim")

    def test_value_with_colon(self):
        text = 'url: https://api.openalex.org?mailto=a@b.org\n'
        v = parse(text)
        self.assertEqual(v["url"], "https://api.openalex.org?mailto=a@b.org")

    def test_bad_indent_raises(self):
        with self.assertRaises(YAMLError):
            parse("a:\n    b: 1\n  c: 2\n")


if __name__ == "__main__":
    unittest.main()
