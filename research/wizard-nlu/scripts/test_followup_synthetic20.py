"""Protocol tests with artificial scores; these are not model-quality measurements."""
import json
import tempfile
import unittest
from pathlib import Path

import followup_synthetic20 as study


def record(confidence, predicted="GOODS", gold="GOODS"):
    return dict(confidence=str(confidence), predicted=predicted, gold=gold)


class FollowupProtocolTests(unittest.TestCase):
    def test_ten_correct_known_answers_enable_the_slot(self):
        rows = [record(.8)] * 10 + [record(.7, gold="EQUIPMENT")]
        cfg = study.strict_slot(rows, .02)
        self.assertEqual(cfg["threshold"], .8)
        self.assertEqual(cfg["dev_accepted"], 10)
        self.assertEqual(cfg["temperature"], .02)

    def test_unknown_cannot_supply_the_minimum_answer_count(self):
        rows = [record(.8)] * 9 + [record(.99, "UNKNOWN", "UNKNOWN")] * 30
        self.assertEqual(study.strict_slot(rows, 1)["threshold"], 1.01)

    def test_confident_error_cannot_be_hidden_by_lower_threshold(self):
        rows = [record(.8)] * 20 + [record(.99, gold="EQUIPMENT")]
        self.assertEqual(study.strict_slot(rows, 1)["dev_accepted"], 0)

    def test_changed_seal_stops_before_inference(self):
        with tempfile.TemporaryDirectory() as directory:
            out = Path(directory) / "study"
            study.prepare(out)
            seal = json.loads((out / "seal.json").read_text())
            seal["hashes"]["dataset/followup_synthetic20.jsonl"] = "changed"
            (out / "seal.json").write_text(json.dumps(seal))
            with self.assertRaises(AssertionError):
                study.run(out)
            self.assertFalse((out / "inference_started.json").exists())

    def test_existing_attempt_cannot_silently_run_again(self):
        with tempfile.TemporaryDirectory() as directory:
            out = Path(directory) / "study"
            before = {str(p): study.digest(p) for p in [study.BASE, study.LAYA, study.DEV]}
            study.prepare(out)
            (out / "inference_started.json").write_text("{}")
            with self.assertRaises(FileExistsError):
                study.run(out)
            self.assertEqual(before, {str(p): study.digest(p) for p in [study.BASE, study.LAYA, study.DEV]})


if __name__ == "__main__":
    unittest.main()
