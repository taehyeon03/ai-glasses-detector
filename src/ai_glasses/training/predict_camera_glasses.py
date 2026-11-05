"""Run the saved quick pilot on one image."""
import argparse
import json
from pathlib import Path
import torch
from PIL import Image,ImageOps
from torchvision import transforms
from torchvision.models import resnet18

def predict(model_path,image_path):
    checkpoint=torch.load(model_path,map_location='cpu',weights_only=True)
    model=resnet18(weights=None);model.fc=torch.nn.Linear(model.fc.in_features,2);model.load_state_dict(checkpoint['model']);model.eval()
    transform=transforms.Compose([transforms.Resize((224,224)),transforms.ToTensor(),transforms.Normalize(checkpoint['normalization']['mean'],checkpoint['normalization']['std'])])
    with Image.open(image_path) as im:x=transform(ImageOps.exif_transpose(im).convert('RGB')).unsqueeze(0)
    with torch.inference_mode():score=model(x).softmax(1)[0,1].item()
    return dict(image=str(image_path),camera_score=score,threshold=.5,prediction='카메라 안경 의심' if score>=.5 else '일반 안경',full_fit=checkpoint.get('full_fit',False),note='합성 이미지로 시험한 모델입니다. 실제 착용 사진의 성능은 측정하지 않았습니다.')

if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--model',type=Path,required=True);parser.add_argument('image',type=Path);args=parser.parse_args();print(json.dumps(predict(args.model,args.image),ensure_ascii=False,indent=2))
