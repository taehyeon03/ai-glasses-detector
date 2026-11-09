# 학습 상태 기록

최종 갱신: 2026-11-09

## 확인된 베이스라인

| 항목 | 확인된 내용 |
| --- | --- |
| 모델 | YOLO26 nano classification |
| 가중치 | `yolo26n-cls.pt` |
| 과업 | 이진 이미지 분류 |
| 실행 환경 | RTX 5070 Ti |
| 실험 추적 | Weights & Biases run `qgrvyb7t` (2026-11-04) |

`-cls` 모델은 이미지 전체를 분류한다. 안경 위치를 표시하는 객체 검출 모델은 아니므로, YOLOE 기반 ROI 추출과 MobileCLIP 비교는 후속 실험 후보로 구분한다.

## W&B 기록 해석

로컬 W&B 설정에는 `binary classification`이 남아 있다. 다만 보존된 로그에는 epoch, metric, `best.pt`, `last.pt`가 없고 run이 초기화 직후 종료됐다. 따라서 이 저장소는 학습 완료나 성능 수치를 주장하지 않는다.

최종 체크포인트와 결과가 확인되면 다음 항목을 추가한다.

- 데이터셋 버전과 클래스별 수량
- 학습 명령, epoch, 입력 크기와 증강 설정
- 검증 지표와 confusion matrix
- `best.pt`의 보관 위치와 SHA-256
- Jetson Nano 배포용 ONNX/TensorRT 변환 결과

## 발표 반영 기준

- 완료·확인됨: YOLO26n 베이스라인 가중치, 이진 분류 W&B 실행 기록, 데이터 수집·검수 작업
- 진행 중: 최종 체크포인트 회수, 성능 평가, Jetson Nano 배포
- 검증 전: 정확도, 재현율, FPS와 객체 위치 검출 성능
