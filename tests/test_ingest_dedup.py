import json
import unittest

from research_library import db, ingest
from research_library.dedup import find_existing, find_possible_duplicates

from helpers import make_tmp_dir


def make_conn():
    return db.connect(make_tmp_dir("db-") / "test.sqlite")


def rec(**kw):
    base = {
        "title": "Executive Functions",
        "authors": [{"name": "Adele Diamond", "given": "Adele", "family": "Diamond", "orcid": None}],
        "publication_year": 2013,
        "publication_date": "2013-09-30",
        "journal_or_publisher": "Annual Review of Psychology",
        "source_urls": ["https://example.org/a"],
    }
    base.update(kw)
    return base


class IngestDedupTest(unittest.TestCase):
    def setUp(self):
        self.conn = make_conn()

    def test_create_and_doi_merge(self):
        r1 = ingest.ingest(self.conn, rec(doi="10.1146/test.1"), source_name="openalex",
                           raw_payload={"a": 1}, domains=["child_development"], tags=["ef"],
                           record_status="candidate")
        self.assertEqual(r1["action"], "created")
        r2 = ingest.ingest(self.conn, rec(doi="https://doi.org/10.1146/TEST.1",
                                          volume="64", abstract="An overview."),
                           source_name="crossref", raw_payload={"b": 2},
                           domains=["learning_sciences"], tags=["cognitive_control"])
        self.assertEqual(r2["action"], "merged")
        self.assertEqual(r2["internal_id"], r1["internal_id"])
        row = db.row_to_dict(db.get_work(self.conn, r1["internal_id"]))
        self.assertEqual(row["volume"], "64")
        self.assertEqual(row["abstract"], "An overview.")
        self.assertEqual(row["research_domains"], ["child_development", "learning_sciences"])
        self.assertEqual(row["topic_tags"], ["ef", "cognitive_control"])
        self.assertIn("openalex", row["raw_sources"])
        self.assertIn("crossref", row["raw_sources"])
        self.assertEqual(row["source_urls"], ["https://example.org/a"])

    def test_conservative_no_doi_merge(self):
        a = ingest.ingest(self.conn, rec(), source_name="openalex", record_status="candidate")
        b = ingest.ingest(self.conn, rec(), source_name="eric", record_status="candidate")
        self.assertEqual(a["internal_id"], b["internal_id"])
        self.assertEqual(b["action"], "merged")

    def test_no_doi_different_works_not_merged(self):
        a = ingest.ingest(self.conn, rec(), source_name="openalex")
        b = ingest.ingest(self.conn, rec(title="Emotion Regulation in Children",
                                         authors=[{"name": "Other Author", "given": None,
                                                   "family": None, "orcid": None}]),
                          source_name="openalex")
        self.assertNotEqual(a["internal_id"], b["internal_id"])

    def test_fuzzy_possible_duplicate_flagged_not_merged(self):
        ingest.ingest(self.conn, rec(), source_name="openalex")
        near = ingest.ingest(self.conn, rec(title="Executive Functionss",
                                            authors=[{"name": "A. Diamond", "given": "A.",
                                                      "family": "Diamond", "orcid": None}]),
                             source_name="openalex")
        self.assertEqual(near["action"], "flagged")
        row = db.get_work(self.conn, near["internal_id"])
        self.assertEqual(row["human_review_required"], 1)
        self.assertIn("possible duplicate", row["ingestion_notes"])

    def test_find_existing_methods(self):
        ingest.ingest(self.conn, rec(doi="10.1000/x"), source_name="s")
        row, method = find_existing(self.conn, doi="10.1000/x", title="Executive Functions",
                                    year=2013, authors_json=rec()["authors"])
        self.assertEqual(method, "doi")
        row, method = find_existing(self.conn, doi=None, title="Executive Functions!",
                                    year=2013, authors_json=rec()["authors"])
        self.assertEqual(method, "conservative")

    def test_possible_duplicates_never_auto_merge(self):
        ingest.ingest(self.conn, rec(), source_name="s")
        poss = find_possible_duplicates(self.conn, title="Executive Functions (Review)",
                                        year=2013, authors_json=rec()["authors"])
        self.assertEqual(poss, [])

    def test_year_conflict_marks_review(self):
        ingest.ingest(self.conn, rec(doi="10.1000/y", publication_year=2013), source_name="a")
        res = ingest.ingest(self.conn, rec(doi="10.1000/y", publication_year=2014), source_name="b")
        self.assertEqual(res["action"], "merged")
        row = db.get_work(self.conn, res["internal_id"])
        self.assertEqual(row["human_review_required"], 1)
        self.assertIn("publication_year differs", row["conflicting_metadata"])

    def test_evidence_category_guess(self):
        self.assertEqual(ingest.guess_evidence_category("A meta-analysis of X"), "meta_analysis")
        self.assertEqual(ingest.guess_evidence_category("A systematic review of Y"),
                         "systematic_review")
        self.assertEqual(ingest.guess_evidence_category("A randomized controlled trial of Z"), "rct")
        self.assertEqual(ingest.guess_evidence_category("Random stuff", "review_article"),
                         "narrative_review")
        self.assertEqual(ingest.guess_evidence_category("Random stuff", "journal_article"),
                         "other_empirical")

    def test_retracted_flagged(self):
        res = ingest.ingest(self.conn, rec(doi="10.1000/r", is_retracted=True), source_name="s")
        row = db.get_work(self.conn, res["internal_id"])
        self.assertEqual(row["retraction_status"], "retracted")
        self.assertEqual(row["human_review_required"], 1)

    def test_id_collision_gets_suffix(self):
        # two different works that hash to the same internal_id base are
        # extremely unlikely; force the path by ingesting two works with the
        # same title but different authors and no DOI-safe identifiers
        a = ingest.ingest(self.conn, rec(title="Same Title", authors=[{"name": "A One", "given": None, "family": None, "orcid": None}]), source_name="s")
        b = ingest.ingest(self.conn, rec(title="Same Title", authors=[{"name": "B Two", "given": None, "family": None, "orcid": None}]), source_name="s")
        self.assertNotEqual(a["internal_id"], b["internal_id"])


if __name__ == "__main__":
    unittest.main()
