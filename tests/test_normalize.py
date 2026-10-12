import json
import unittest

from research_library.normalize import (
    first_surname, guess_year, norm_authors, norm_doi, norm_title,
    safe_internal_id, split_name, title_similarity,
)


class NormalizeTest(unittest.TestCase):
    def test_norm_doi(self):
        self.assertEqual(norm_doi("https://doi.org/10.1234/ABC.def"), "10.1234/abc.def")
        self.assertEqual(norm_doi("DOI: 10.1234/X.1"), "10.1234/x.1")
        self.assertEqual(norm_doi("10.1037/0033-295X.84.2.191"), "10.1037/0033-295x.84.2.191")
        self.assertIsNone(norm_doi("not-a-doi"))
        self.assertIsNone(norm_doi(None))

    def test_norm_title(self):
        self.assertEqual(norm_title("Executive Functions!"), "executive functions")
        self.assertEqual(norm_title("The 'What' and 'Why' of Goal Pursuits"),
                         "the what and why of goal pursuits")
        self.assertEqual(norm_title("执行功能：认知发展"), "执行功能 认知发展")

    def test_split_name(self):
        self.assertEqual(split_name("Smith, John A."), ("Smith", "John A."))
        self.assertEqual(split_name("John Smith"), ("Smith", "John"))
        self.assertEqual(split_name("王小明"), (None, None))
        self.assertEqual(split_name("Cher"), ("Cher", None))

    def test_norm_authors_openalex(self):
        raw = [{"author": {"display_name": "Adele Diamond", "orcid": "https://orcid.org/0000-0002-1825-0097"}}]
        out = norm_authors(raw, "openalex")
        self.assertEqual(out[0]["name"], "Adele Diamond")
        self.assertEqual(out[0]["family"], "Diamond")
        self.assertEqual(out[0]["orcid"], "0000-0002-1825-0097")

    def test_norm_authors_crossref(self):
        raw = [{"given": "Adele", "family": "Diamond"}]
        out = norm_authors(raw, "crossref")
        self.assertEqual(out[0]["name"], "Adele Diamond")

    def test_first_surname(self):
        authors = norm_authors([{"author": {"display_name": "Adele Diamond"}}], "openalex")
        self.assertEqual(first_surname(authors), "diamond")
        zh = [{"name": "王小明", "given": None, "family": None, "orcid": None}]
        self.assertIsNone(first_surname(zh))

    def test_title_similarity(self):
        self.assertGreater(title_similarity("Executive Functions", "executive  functions"),
                           0.95)
        self.assertLess(title_similarity("Executive Functions", "Totally different paper"),
                        0.5)

    def test_guess_year_and_internal_id(self):
        self.assertEqual(guess_year("2013-09-30"), 2013)
        self.assertEqual(guess_year(None, "published 2018"), 2018)
        id1 = safe_internal_id("10.1234/x", None)
        id2 = safe_internal_id(None, "Some Title Here")
        self.assertTrue(id1.startswith("lt-") and len(id1) == 15)
        self.assertEqual(id2, safe_internal_id(None, "some  title! here"))
        self.assertNotEqual(id1, id2)

    def test_json_roundtrip_authors(self):
        authors = norm_authors([{"given": "John", "family": "Smith"}], "crossref")
        loaded = json.loads(json.dumps(authors))
        self.assertEqual(first_surname(loaded), "smith")


if __name__ == "__main__":
    unittest.main()
