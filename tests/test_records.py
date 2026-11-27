import unittest
from pipeline.records import audit_splits, metrics


class RecordTests(unittest.TestCase):
    def test_metrics_use_true_rows_and_predicted_columns(self):
        result = metrics([0, 0, 0, 1, 1], [0, 1, 1, 1, 0], 0.8)
        self.assertEqual(result["confusion_matrix"], [[1, 2], [1, 1]])
        self.assertAlmostEqual(result["false_positive_rate"], 2 / 3)
        self.assertAlmostEqual(result["camera_recall"], 0.5)
        self.assertAlmostEqual(result["macro_f1"], (0.4 + 0.4) / 2)

    def test_missing_predictions_are_rejected(self):
        with self.assertRaises(ValueError):
            metrics([0, 1], [0], 0)

    def test_leakage_is_rejected(self):
        row = {key: "shared" for key in ["sample_id", "identity_group_id",
               "regeneration_family_id", "portrait_reference_sha256", "image_sha256"]}
        with self.assertRaisesRegex(ValueError, "leakage"):
            audit_splits({"train": [row], "test": [row]})


if __name__ == "__main__":
    unittest.main()
