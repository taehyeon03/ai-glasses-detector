# AI Glasses Detector

시험장 입구에서 Jetson Nano 4GB + CSI 카메라(IMX219)로 입실자의 안경 착용 상태를 실시간 분류하는 임베디드 비전 시스템.

- 클래스: 없음 / 일반 안경 / AI(스마트) 안경
- 추론: PC 학습 → ONNX → TensorRT FP16 (JetPack 4.6)
- 출력: 개발 중 웹 스트림(SSH), 최종 USB 스피커 음성 안내

요구계획서: [docs/requirements.md](docs/requirements.md)

> 판정은 감독관 보조용이다. 크롤링 이미지·얼굴 데이터는 이 저장소에 올리지 않는다.

## RTX에서 생성·검수·학습하는 코드

기존 Jetson 요구사항과 별도로, 이 코드는 참고 사진으로 착용 이미지를 생성하고 웹에서 검수합니다. 검수를 통과한 이미지로 카메라 안경과 일반 안경을 구분하는 YOLO 분류 모델을 학습할 수 있습니다.

| 경로 | 역할 |
|---|---|
| `src/ai_glasses/generation/` | 제품별 프롬프트, 참고 사진, 생성 대기열과 작업 실행 |
| `src/ai_glasses/review/` | 검수 웹 화면, 서버, 판정과 배정 관리 |
| `src/ai_glasses/training/` | 데이터 분리, 학습, 평가와 추론 |
| `src/ai_glasses/utils/` | 원본 등록, 얼굴 크롭, 감사와 동기화 |
| `src/ai_glasses/legacy/` | 이전 실험과 일회성 운영 도구 |
| `ops/` | 실행 스크립트와 서비스 설정 예시 |
| `tests/` | 단위 테스트와 가짜 이미지 생성 코드 |
| `data/` | 로컬 전용 데이터. 기본 저장 위치는 `TRYON_ROOT`로 바꿀 수 있습니다. |

### 데이터 없이 검수 화면 실행

Python 3.10 이상과 Pillow가 필요합니다. 저장소 루트에서 아래 명령을 실행하면 임시 폴더에 가짜 사진 2장이 생깁니다.

```bash
python -m pip install -e .
export TRYON_ROOT="$(mktemp -d)"
PYTHONPATH=src python tests/fixtures/demo_review.py
./ops/run review.public_review_server
```

브라우저에서 `http://127.0.0.1:8790/`를 열고 검수자를 선택합니다.

```bash
PYTHONPATH=src python -m unittest discover -s tests
```

자세한 실행 순서와 경로 설정은 [운영 안내](docs/pipeline.md)에 있습니다.
