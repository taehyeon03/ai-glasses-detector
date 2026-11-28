# AI Glasses Detector

## 현재 실험 기준 (2026-11-27)

현재 과업은 카메라가 있는 안경과 일반 안경의 이진 분류다.
데이터는 [Hugging Face](https://huggingface.co/datasets/KTH03/camera-glasses-research-20261127)에 있다.
학습에는 7,000장을 사용한다.
검증에는 1,500장을 사용한다.
최종 테스트에는 1,500장을 사용한다.
제품은 여러 분할에 등장한다.
현재 데이터에는 안경을 쓰지 않은 클래스가 없다.
현재 데이터에는 카메라가 없는 스마트 안경도 없다.

[AGENTS.md](AGENTS.md)는 모든 실험에 적용된다.
[실험 규약](docs/experiment-protocol.md)은 공통 로그 형식을 설명한다.
공통 파이프라인은 `python -m pipeline.probe --config CONFIG.json --run runs/UNIQUE_ID`로 실행한다.
환경은 `requirements-research.txt`를 참고해서 PC에 마련한다.
실험 설정과 해석은 각 실험 브랜치에 기록한다.
이미지와 체크포인트는 Git에 포함하지 않는다.
실제 Jetson Nano 4GB에서의 검증은 아직 필요하다.
카메라 안경 실물 없이 공개 영상으로 시험하는 방법은 [YouTube 테스트 세트](youtube_test/README.md)에 있다.

아래 내용과 기존 요구계획서는 초기 계획을 보존한 기록이다.
현재 실험의 클래스와 데이터 기준은 위 설명을 따른다.

시험장 입구에서 Jetson Nano 4GB + CSI 카메라(IMX219)로 입실자의 안경 착용 상태를 실시간 분류하는 임베디드 비전 시스템.

- 클래스: 없음 / 일반 안경 / AI(스마트) 안경
- 추론: PC 학습 → ONNX → TensorRT FP16 (JetPack 4.6)
- 출력: 개발 중 웹 스트림(SSH), 최종 USB 스피커 음성 안내

요구계획서: [docs/requirements.md](docs/requirements.md)

현재 학습 상태와 발표 반영 기준: [docs/training-status.md](docs/training-status.md)

> 판정은 감독관 보조용이다. 크롤링 이미지·얼굴 데이터는 이 저장소에 올리지 않는다.
