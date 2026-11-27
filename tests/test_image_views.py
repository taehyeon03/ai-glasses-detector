import subprocess
import sys
import unittest

import numpy as np
from PIL import Image

from pipeline import image_views
from pipeline.mobile_data import geometry
from pipeline.part_data import local_views


class ImageViewTests(unittest.TestCase):
    def test_cpu_preprocessing_matches_training_preprocessing(self):
        face=np.asarray([20,30,180,180,80,100,140,100,110,130,90,150,130,150,.99])
        info=geometry(face)
        self.assertEqual(info,image_views.geometry(face))
        image=Image.fromarray(np.arange(320*240*3,dtype=np.uint8).reshape(320,240,3))
        expected=local_views(image,info)
        actual=image_views.local_views(image,info)
        for a,b in zip(expected[:3],actual[:3]):np.testing.assert_array_equal(a,b)
        self.assertEqual(expected[3],actual[3])

    def test_lightweight_preprocessing_does_not_import_torch(self):
        subprocess.check_call([sys.executable,"-c","import pipeline.image_views,sys; assert 'torch' not in sys.modules"])


if __name__=="__main__":unittest.main()
