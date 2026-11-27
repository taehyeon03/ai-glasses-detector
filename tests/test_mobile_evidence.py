import unittest

import torch
from torch import nn

from pipeline.mobile_evidence import add_bridge_region, gradcam, select_cases


class LinearSpatialModel(nn.Module):
    def __init__(self):
        super().__init__()
        self.features = nn.Sequential(nn.Conv2d(3,2,1,bias=False), *[nn.Identity() for _ in range(12)])
        self.head = nn.Linear(2,2,bias=False)
        with torch.no_grad():
            self.features[0].weight.zero_()
            self.features[0].weight[0,0,0,0] = 1
            self.features[0].weight[1,1,0,0] = 1
            self.head.weight.copy_(torch.tensor([[0.,0.],[2.,-1.]]))

    def forward(self, images):
        return self.head(self.features(images).mean((2,3)))


class EvidenceTests(unittest.TestCase):
    def test_bridge_region_does_not_change_the_training_geometry(self):
        geometry = dict(landmarks=[[80,100],[140,100],[110,130],[90,150],[130,150]],
                        regions={"glasses":[40,60,180,130]})
        augmented = add_bridge_region(geometry)
        self.assertNotIn("bridge",geometry["regions"])
        self.assertIn("bridge",augmented["regions"])
        x0,y0,x1,y1 = augmented["regions"]["bridge"]
        self.assertTrue(x0 < 110 < x1)
        self.assertTrue(y0 < 89.2 < y1)

    def test_cam_matches_known_linear_spatial_contributions(self):
        network = LinearSpatialModel().eval().requires_grad_(False)
        images = torch.arange(48.).reshape(1,3,4,4)
        expected = (2*images[:,0]-images[:,1])/16
        logits,cams = gradcam(network,images)
        torch.testing.assert_close(cams[8],expected)
        torch.testing.assert_close(cams[12],expected)
        with torch.no_grad():
            network.head.weight.copy_(network.head.weight.flip(0))
        _,swapped = gradcam(network,images)
        torch.testing.assert_close(swapped[8],-expected)
        self.assertEqual(len(network.features[8]._forward_hooks),0)

    def test_occlusion_selection_is_balanced_and_reproducible(self):
        rows = [dict(label=label,product_id=str(label)+str(i%2),geometry={})
                for label in [0,1] for i in range(8)]
        predictions = [dict(prediction=i%2) for i in range(16)]
        selected = select_cases(rows,predictions,6)
        self.assertEqual(selected,select_cases(rows,predictions,6))
        self.assertEqual(len(set(selected)),6)
        self.assertEqual(sum(rows[i]["label"]==1 for i in selected),3)
        self.assertEqual(len({rows[i]["product_id"] for i in selected}),4)


if __name__=="__main__":
    unittest.main()
