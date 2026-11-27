import unittest

from pipeline.camera_annotations import validate_annotation


class AnnotationTests(unittest.TestCase):
    def row(self,label=1):
        return dict(sample_id="s",product_id="p",split="validation",label=label)

    def value(self):
        return dict(reviewer="test",visibility="visible",reference_checked=True,
                    objects=[dict(kind="camera_aperture",box=[10,20,18,28])])

    def test_visible_camera_requires_an_actual_box(self):
        value=self.value();value["objects"]=[]
        with self.assertRaises(ValueError):validate_annotation(value,self.row(),100,100)

    def test_hidden_camera_cannot_receive_an_invented_box(self):
        value=self.value();value["visibility"]="occluded"
        with self.assertRaises(ValueError):validate_annotation(value,self.row(),100,100)

    def test_class_conflict_is_held_for_review(self):
        result=validate_annotation(self.value(),self.row(0),100,100)
        self.assertTrue(result["label_conflict"])
        self.assertEqual(result["status"],"needs_review")

    def test_reference_check_is_required_for_confirmation(self):
        value=self.value();value["reference_checked"]=False
        self.assertEqual(validate_annotation(value,self.row(),100,100)["status"],"needs_review")


if __name__=="__main__":unittest.main()
