"""Project-specific models. Region weights are not certified explanations."""
import sys

import torch
import torch.nn.functional as F
from torch import nn
from torchvision.models import MobileNet_V3_Small_Weights,mobilenet_v3_small

from pipeline.mobile_train import normalize


class PartEvidenceNet(nn.Module):
    def __init__(self,mode,pretrained=True):
        super().__init__()
        self.mode=mode
        weights=MobileNet_V3_Small_Weights.IMAGENET1K_V1 if pretrained else None
        self.features=mobilenet_v3_small(weights=weights).features
        self.project=nn.Sequential(nn.Linear(576,128),nn.ReLU())
        self.gate=nn.Sequential(nn.Linear(128*2+4,64),nn.ReLU(),nn.Linear(64,1))
        self.classifier=nn.Sequential(nn.Linear(256,128),nn.ReLU(),nn.Dropout(.2),nn.Linear(128,2))

    def train(self,mode=True):
        super().train(mode)
        # Shared views have different sizes. Keep common ImageNet BN statistics fixed.
        for module in self.features.modules():
            if isinstance(module,nn.BatchNorm2d):
                module.eval()
        return self

    def encode(self,images):
        return self.project(self.features(normalize(images)).mean((2,3)))

    def forward_with_weights(self,global_image,parts,quality,valid):
        global_features=self.encode(global_image)
        if self.mode=="matched_global":
            weights=global_features.new_zeros((global_image.shape[0],3))
            local_features=torch.zeros_like(global_features)
        else:
            n=global_image.shape[0]
            local=self.encode(parts.reshape(n*3,3,parts.shape[-2],parts.shape[-1])).reshape(n,3,128)
            if self.mode=="parts_mean":
                weights=valid/valid.sum(1,keepdim=True).clamp_min(1)
            elif self.mode=="parts_gate":
                expanded=global_features[:,None,:].expand(-1,3,-1)
                scores=self.gate(torch.cat([local,expanded,quality],dim=2)).squeeze(2)
                scores=scores.masked_fill(valid==0,-10000)
                weights=scores.softmax(1)*valid
                weights=weights/weights.sum(1,keepdim=True).clamp_min(1e-8)
            else:
                raise ValueError(self.mode)
            local_features=(local*weights[:,:,None]).sum(1)
        return self.classifier(torch.cat([global_features,local_features],dim=1)),weights

    def forward(self,global_image,parts=None,quality=None,valid=None):
        return self.forward_with_weights(global_image,parts,quality,valid)[0]


class MobileCLIPClassifier(nn.Module):
    def __init__(self,config,frozen):
        super().__init__()
        sys.path.insert(0,config["mobileclip_source"])
        import mobileclip
        network,_,_=mobileclip.create_model_and_transforms("mobileclip_s0",
            pretrained=config["mobileclip_checkpoint"],reparameterize=frozen)
        self.encoder=network.image_encoder
        self.frozen=frozen
        if frozen:
            self.encoder.requires_grad_(False)
        self.head=nn.Linear(512,2)
        del network

    def train(self,mode=True):
        super().train(mode)
        if self.frozen:
            self.encoder.eval()
        return self

    def encode(self,image):
        # MobileCLIP's official transform uses [0,1] without ImageNet normalization.
        return F.normalize(self.encoder(image.float()/255),dim=-1)

    def forward(self,global_image,parts=None,quality=None,valid=None):
        return self.head(self.encode(global_image))


def create(config,pretrained=True):
    mode=config["mode"]
    if mode in ["mobileclip_linear","mobileclip_finetune"]:
        return MobileCLIPClassifier(config,frozen=mode=="mobileclip_linear")
    return PartEvidenceNet(mode,pretrained)
