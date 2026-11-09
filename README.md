# AI Glasses Detector

시험장 입구에서 Jetson Nano 4GB + CSI 카메라(IMX219)로 입실자의 안경 착용 상태를 실시간 분류하는 임베디드 비전 시스템.

- 클래스: 없음 / 일반 안경 / AI(스마트) 안경
- 추론: PC 학습 → ONNX → TensorRT FP16 (JetPack 4.6)
- 출력: 개발 중 웹 스트림(SSH), 최종 USB 스피커 음성 안내

요구계획서: [docs/requirements.md](docs/requirements.md)

현재 학습 상태와 발표 반영 기준: [docs/training-status.md](docs/training-status.md)

> 판정은 감독관 보조용이다. 크롤링 이미지·얼굴 데이터는 이 저장소에 올리지 않는다.
