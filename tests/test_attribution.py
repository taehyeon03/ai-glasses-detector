import unittest
import torch
from pipeline.explain import integrated_gradients, mask_patches


class AttributionTests(unittest.TestCase):
    def test_integrated_gradients_recovers_linear_contributions(self):
        image = torch.tensor([[[[2., 3.]]]])
        baseline = torch.ones_like(image)
        weights = torch.tensor([[[[4., -2.]]]])
        def score(value):
            return (value * weights).sum((1, 2, 3))
        attribution, result = integrated_gradients(score, image, baseline, 4)
        torch.testing.assert_close(attribution, torch.tensor([[[[4., -4.]]]]))
        self.assertEqual(result["completeness_absolute_error"], 0)

    def test_mask_changes_exactly_the_selected_patch(self):
        image = torch.ones(1, 3, 32, 32)
        masked = mask_patches(image, torch.zeros_like(image), [1], 16)
        self.assertEqual((masked == 0).sum().item(), 3 * 16 * 16)
        self.assertEqual(masked[:, :, :16, 16:].sum().item(), 0)
        torch.testing.assert_close(image, torch.ones_like(image))


if __name__ == "__main__":
    unittest.main()
