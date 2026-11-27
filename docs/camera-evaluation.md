# 실제 카메라와 촬영용 렌즈에 대한 평가

## 현재 가능한 범위

사용자는 노트북이나 USB 카메라를 사용할 수 있다.
현재 카메라 안경 실물은 없다.
일반 안경을 착용한 사진에서는 오탐률을 평가할 수 있다.
카메라 안경을 착용한 실제 재현율은 아직 측정할 수 없다.
일반 안경만 평가했을 때 카메라 재현율을 0이나 100으로 기록하지 않는다.
값은 null로 저장한다.

## 동의한 촬영을 기록하기

카메라 프로그램은 사용자가 직접 실행한다.
준비되지 않은 상태에서 카메라를 켜지 않는다.
촬영에 동의한 사람만 포함한다.
공개 저장소에 촬영한 사진을 올리지 않는다.

노트북 환경에는 `requirements-camera.txt`를 설치한다.
이 환경은 PyTorch가 없어도 된다.
`opencv-python-headless`는 촬영 화면을 표시하지 못한다.
노트북에는 GUI를 포함하는 `opencv-python`을 사용한다.

```bash
python -m scripts.capture_camera_sessions --output /PRIVATE/camera-sessions --person-group participant-01 --product ordinary-01 --label ordinary_glasses --domain real_worn --consent-confirmed
```

화면에서 SPACE를 누르면 한 번의 검사를 기록한다.
검사 하나는 1초 간격의 5개 프레임으로 구성한다.
Q를 누르면 종료한다.
프레임 5개를 검사 5회로 세지 않는다.
같은 사람의 세션은 학습과 최종 평가에 나누어 넣지 않는다.
실제 조건을 기록하려면 거리와 조명 및 시점 인수를 추가한다.

화면에 표시한 사진을 재촬영할 때는 `--domain screen_recapture`를 사용한다.
그 결과를 real_worn과 합치지 않는다.
실물 없이 real_worn의 카메라 안경 양성 자료를 기록하려고 하면 프로그램은 중단한다.

## 고정한 모델로 평가하기

검증에서 선택한 체크포인트를 ONNX로 내보낸다.
PC에서 PyTorch의 출력과 ONNX의 출력을 비교한다.
그 검증은 Nano에서의 성공을 뜻하지 않는다.

```bash
python -m scripts.export_proposed_onnx --run /PRIVATE/selected-run --output /PRIVATE/model-bundle
python -m scripts.evaluate_camera_sessions --bundle /PRIVATE/model-bundle --sessions /PRIVATE/camera-sessions --output /PRIVATE/field-evaluation
```

노트북에서 평가할 때는 모델 묶음과 촬영한 자료가 필요하다.
얼굴의 기준점이 검출되지 않으면 재촬영이 필요한 검사로 기록한다.
그 검사를 일반 안경으로 판정하지 않는다.
완료한 검사 비율과 재촬영 비율을 함께 보고한다.
표준 판정은 5개 프레임 점수의 평균에 임계값 0.5를 적용한다.
이 규칙은 실제 평가 전에 고정한다.
다른 규칙은 별도 실험으로 비교한다.
오프라인 사진의 처리 시간은 카메라의 센서 지연을 포함하지 않는다.
Nano에서는 실제 입력부터 결과까지의 지연을 다시 측정한다.

## 촬영용 렌즈의 정답을 표시하기

300장에 대해 사용자 검토용 인터페이스를 준비했다.
촬영용 렌즈의 개구부를 표시한다.
안경의 광학 렌즈도 별도로 표시한다.
장식용 리벳과 표시등을 구분한다.
제품 참고 자료와 대조한 상태를 기록한다.
가려진 카메라에 상상의 박스를 그리지 않는다.
원래 클래스와 충돌하면 검토 대기로 남긴다.
주석은 추가 기록으로 보존한다.
원래 이미지와 릴리스 라벨은 수정하지 않는다.

서버는 5070 Ti에서 loopback에만 연다.

```bash
python -m scripts.annotate_camera_regions --metadata /mnt/data/ai-glasses-research/mobile-views-v1/metadata.json --selection /mnt/data/ai-glasses-research/runs/mobile-evidence-20261127/evidence-v3/occlusion-selection.json --product-manifest /home/kth/.local/share/ai-glasses-datasets/20261127-v1/manifest.csv --output /mnt/data/ai-glasses-research/camera-annotations/validation.jsonl
```

노트북에서 SSH로 연결한다.

```bash
ssh -L 17882:127.0.0.1:17882 5070ti
```

브라우저에서 `http://127.0.0.1:17882`를 연다.
서버가 자동으로 사진의 정답을 확정하지 않는다.
검증 주석은 평가에만 사용한다.
부위에 대한 감독 학습에는 학습 분할의 별도 주석이 필요하다.
