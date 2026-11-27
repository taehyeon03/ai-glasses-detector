import unittest

import torch
from torch import nn

from pipeline.part_model import PartEvidenceNet


class PartTests(unittest.TestCase):
    def setUp(self):
        torch.set_num_threads(2)

    def inputs(self):
        return (torch.randint(0,256,(2,3,64,64),dtype=torch.uint8),
                torch.randint(0,256,(2,3,3,32,32),dtype=torch.uint8),torch.rand(2,3,4),torch.ones(2,3))

    def test_invalid_parts_have_zero_weight_without_nan(self):
        network=PartEvidenceNet("parts_gate",pretrained=False).eval()
        image,parts,quality,valid=self.inputs();valid.zero_()
        logits,weights=network.forward_with_weights(image,parts,quality,valid)
        self.assertTrue(torch.isfinite(logits).all())
        torch.testing.assert_close(weights,torch.zeros_like(weights))

    def test_equal_pooling_ignores_invalid_part(self):
        network=PartEvidenceNet("parts_mean",pretrained=False).eval()
        image,parts,quality,valid=self.inputs();valid[:,1]=0
        _,weights=network.forward_with_weights(image,parts,quality,valid)
        torch.testing.assert_close(weights,torch.tensor([[.5,0,.5],[.5,0,.5]]))

    def test_shared_backbone_receives_gradients_with_bn_statistics_frozen(self):
        network=PartEvidenceNet("parts_gate",pretrained=False).train()
        logits=network(*self.inputs())
        nn.functional.cross_entropy(logits,torch.tensor([0,1])).backward()
        self.assertIsNotNone(network.features[0][0].weight.grad)
        self.assertTrue(all(not m.training for m in network.features.modules() if isinstance(m,nn.BatchNorm2d)))


if __name__=="__main__":
    unittest.main()
