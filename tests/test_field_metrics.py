import unittest

from pipeline.field_metrics import aggregate


class FieldTests(unittest.TestCase):
    def frames(self,label="ordinary_glasses",score=.7,domain="real_worn",inspection="one"):
        return [dict(consent_confirmed=True,domain=domain,session_id="s",inspection_id=inspection,
                     label=label,person_group_id="p",camera_probability=score) for _ in range(5)]

    def test_five_frames_are_one_inspection_and_recall_is_unavailable(self):
        result=aggregate(self.frames())["real_worn"]
        self.assertEqual(result["n_inspections"],1)
        self.assertEqual(result["false_positive_rate"],1)
        self.assertIsNone(result["camera_recall"])

    def test_screen_positives_do_not_create_real_worn_recall(self):
        result=aggregate(self.frames()+self.frames("camera_glasses",.8,"screen_recapture"))
        self.assertIsNone(result["real_worn"]["camera_recall"])
        self.assertEqual(result["screen_recapture"]["camera_recall"],1)

    def test_missing_geometry_requires_retry(self):
        frames=self.frames();frames[0]["camera_probability"]=None
        result=aggregate(frames)["real_worn"]
        self.assertEqual(result["n_scored"],0)
        self.assertEqual(result["retry_rate"],1)

    def test_incomplete_inspection_is_not_counted_as_success(self):
        result=aggregate(self.frames()[:3])["real_worn"]
        self.assertEqual(result["n_scored"],0)
        self.assertEqual(result["incomplete_inspections"],1)


if __name__=="__main__":
    unittest.main()
