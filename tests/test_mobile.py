import unittest

import numpy as np
import torch
from PIL import Image

from pipeline.mobile_data import clip_box, matched_views
from pipeline.mobile_train import model, normalize


class MobileTests(unittest.TestCase):
    def test_matched_mask_preserves_the_glasses_pixels(self):
        pixels = np.arange(24 * 24 * 3, dtype=np.uint8).reshape(24, 24, 3)
        original = Image.fromarray(pixels)
        views = matched_views(original, {"roi": [4, 6, 18, 16]}, 24)
        np.testing.assert_array_equal(views["full"][6:16, 4:18], views["roi_mask"][6:16, 4:18])
        np.testing.assert_array_equal(views["roi_mask"][0, 0], [123, 116, 104])
        self.assertEqual(views["roi_crop"].shape, (24, 24, 3))

    def test_failed_detector_uses_the_same_input_for_every_condition(self):
        views = matched_views(Image.new("RGB", (80, 60), "red"), None, 24)
        np.testing.assert_array_equal(views["full"], views["roi_crop"])
        np.testing.assert_array_equal(views["full"], views["roi_mask"])

    def test_boxes_stay_inside_the_image(self):
        self.assertEqual(clip_box([-12, -10, 300, 260]), [0, 0, 224, 224])

    def test_binary_network_can_train_all_layers(self):
        torch.set_num_threads(2)
        network = model(pretrained=False)
        network.train()
        images = torch.randint(0, 256, (2, 3, 64, 64), dtype=torch.uint8)
        loss = torch.nn.functional.cross_entropy(network(normalize(images)), torch.tensor([0, 1]))
        loss.backward()
        self.assertIsNotNone(network.features[0][0].weight.grad)
        self.assertEqual(network.classifier[-1].out_features, 2)


if __name__ == "__main__":
    unittest.main()
