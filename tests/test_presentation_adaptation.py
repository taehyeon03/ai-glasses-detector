import unittest

import torch

from pipeline.presentation_adaptation import predict


class AdapterTests(unittest.TestCase):
    def test_zero_weight_recovers_the_same_clip_logits(self):
        features=torch.tensor([[1.,0.],[0.,1.]])
        expected=2*features
        actual=predict(features,torch.eye(2),2.,torch.eye(2),torch.eye(2),alpha=0,beta=5)
        torch.testing.assert_close(actual,expected)

    def test_cache_adds_more_support_to_matching_examples(self):
        logits=predict(torch.eye(2),torch.eye(2),2.,torch.eye(2),torch.eye(2),alpha=3,beta=1)
        torch.testing.assert_close(logits.diag(),torch.tensor([5.,5.]))
        self.assertGreater(logits[0,0].item(),logits[0,1].item())


if __name__=="__main__":unittest.main()
