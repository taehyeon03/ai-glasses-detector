# YouTube 테스트 세트

카메라 안경 실물 없이 공개 영상의 착용 장면으로 모델을 확인한다.
이 폴더에는 영상 주소와 구간과 정답만 둔다.
영상과 프레임과 체크포인트는 Git에 올리지 않는다.
모든 사람이 같은 구간으로 비교하도록 세트를 고정한다.

## 파일

- `v1.json`: 영상 19개와 구간 90개, 합계 29:39
- `training-products-20261127.json`: 학습 데이터의 제품 77개 목록이다. 5070 Ti의 데이터 manifest에서 제품 이름과 분할별 장수만 뽑았다.

## v1 구성

| 학습 제품과의 관계 | 길이 |
|---|---|
| in_training (카메라 안경) | 5:45 |
| same_family (카메라 안경) | 3:50 |
| ood (카메라 안경과 일반 안경) | 15:30 |
| not_applicable (안경 없음) | 4:34 |

정답별로는 카메라 안경 14:18, 일반 안경 10:47, 안경 없음 4:34이다.
현재 세트의 일반 안경은 모두 학습 데이터에 없는 제품이다.
그래서 일반 안경의 오탐률은 ood로만 측정된다.

## 검증 상태

모든 구간의 모든 초를 1 fps 프레임 묶음으로 확인했다.
정해진 상태가 유지되는 초만 남기도록 구간을 잘랐다.
B-roll과 제품 클로즈업과 안경을 벗은 장면은 구간에서 뺐다.
이 확인은 Claude가 했다.
그래서 모든 영상의 `review.status`는 `pending_human_review`다.
사람이 영상을 보고 확인한 뒤에만 `confirmed`로 바꾼다.

제품의 정체는 영상마다 근거의 수준이 다르다.
`product_evidence`에 근거를 적었다.
카메라 개구부를 확대해서 확인한 영상은 Xiaomi와 Ray-Ban Meta 두 개다.
Ray-Ban Meta의 세대와 스타일은 제목이나 화면 자막에 의존한다.
Brilliant Labs Halo는 제목에만 의존한다.
일반 안경은 제목의 브랜드와 프레임에 카메라 모듈이 보이지 않는다는 점만 확인했다.

| 영상 | 제품 | 학습 관계 | 대응하는 학습 제품 | 정답별 길이 | 제품 근거 |
|---|---|---|---|---|---|
| [rayban-meta-gen1-1yr](https://www.youtube.com/watch?v=X95mWoTgjaE) | Ray-Ban Meta Wayfarer (Gen 1), sunglasses | same_family | Ray-Ban Meta Gen 2 Wayfarer, Ray-Ban Meta Gen 2 Skyler, Ray-Ban Meta Gen 2 Headliner | 카메라 0:24 | camera aperture visible at hinge in 1:45-1:49 close-up; generation from video title, not verified |
| [oakley-meta-hstn-review](https://www.youtube.com/watch?v=xnUVYvzGAxw) | Oakley Meta HSTN | in_training | Oakley Meta HSTN | 카메라 0:32 | video title names the product; frame shape matches HSTN |
| [xiaomi-ai-3wk](https://www.youtube.com/watch?v=gRmj-5Q6utM) | Xiaomi AI Glasses | in_training | Xiaomi AI Glasses | 카메라 2:40 | camera aperture at hinge visible in full-resolution crop at 0:40 |
| [rayban-meta-2yr](https://www.youtube.com/watch?v=ePyyY9k1uXc) | Ray-Ban Meta (Gen 1/2) / presenter mostly without glasses | same_family | Ray-Ban Meta Gen 2 Wayfarer, Ray-Ban Meta Gen 2 Skyler, Ray-Ban Meta Gen 2 Headliner | 카메라 0:04, 없음 0:36 | video title only; Wayfarer-shaped sunglasses, generation not verified |
| [rayban-meta-fulltime-eyeguy](https://www.youtube.com/watch?v=yLreaz4F6Kk) | Ray-Ban Meta Wayfarer, clear Rx lens | same_family | Ray-Ban Meta Gen 2 Wayfarer, Ray-Ban Meta Gen 2 Skyler, Ray-Ban Meta Gen 2 Headliner | 카메라 2:10 | camera apertures at both hinges visible in full-resolution crop at 1:48; generation not verified |
| [rayban-meta-6mo](https://www.youtube.com/watch?v=ViA4-YWx8Y4) | Ray-Ban Meta Wayfarer (Gen 1), sunglasses | same_family | Ray-Ban Meta Gen 2 Wayfarer, Ray-Ban Meta Gen 2 Skyler, Ray-Ban Meta Gen 2 Headliner | 카메라 0:15, 없음 0:14 | product close-up with camera at 0:46 in the same video |
| [rayban-meta-gen2-week](https://www.youtube.com/watch?v=xegFRQPotuQ) | Ray-Ban Meta (Gen 2), clear lens | in_training | Ray-Ban Meta Gen 2 Wayfarer | 카메라 0:40, 없음 0:07 | video title says Gen 2; Ray-Ban logo close-up at 1:14; style not verified |
| [oakley-meta-vanguard](https://www.youtube.com/watch?v=kRmmhOUwwM4) | Oakley Meta Vanguard (center camera) | in_training | Oakley Meta Vanguard | 카메라 0:09, 없음 0:33 | video title and product unboxing in the same video |
| [rayban-meta-gen2-6mo](https://www.youtube.com/watch?v=Mzw7qgnp2PM) | Ray-Ban Meta (Gen 2), sunglasses | in_training | Ray-Ban Meta Gen 2 Wayfarer | 카메라 0:36, 없음 0:34 | video title says Gen 2; style not verified |
| [solos-airgo-vision](https://www.youtube.com/watch?v=mcRgqwAnFtY) | Solos AirGo Vision (camera on temple module) | same_family | Solos AirGo V2 Prime 1, Solos AirGo V Krypton 1 | 카메라 0:57 | video title names AirGo Vision; camera module on the frame front visible in product shots |
| [rayban-meta-gen2-nyc](https://www.youtube.com/watch?v=PXferOAgzhs) | Ray-Ban Meta (Gen 2), sunglasses and clear lens | in_training | Ray-Ban Meta Gen 2 Wayfarer | 카메라 1:08 | on-screen caption says shot on Ray-Ban Meta Gen 2; style not verified |
| [meta-rayban-display-6mo](https://www.youtube.com/watch?v=Kuf9qb0_W8I) | Meta Ray-Ban Display (with Neural Band) | ood | – | 카메라 2:44 | video title names Meta Ray-Ban Display; product shots in the same video |
| [brilliant-halo-part3](https://www.youtube.com/watch?v=bWQiBroTpu8) | Brilliant Labs Halo (tinted) | ood | – | 카메라 1:59 | video title only; the worn tinted pair is assumed to be Halo, not verified |
| [zeelool-face-shape](https://www.youtube.com/watch?v=3jOMFI4XYCg) | Zeelool frames (try-on) | ood | – | 일반 2:04, 없음 0:40 | brand from video title; no camera module visible on worn frames |
| [zeelool-haul](https://www.youtube.com/watch?v=EqSzjuy_fXY) | Zeelool frames (try-on) | ood | – | 일반 0:57, 없음 0:23 | brand from video title; no camera module visible on worn frames |
| [warby-parker-try-on](https://www.youtube.com/watch?v=LGI2G8ZUWP8) | Warby Parker home try-on | ood | – | 일반 0:48, 없음 1:27 | brand from video title; no camera module visible on worn frames |
| [warby-parker-haul-7](https://www.youtube.com/watch?v=b8XKdNcSsTo) | Warby Parker frames (haul) | ood | – | 일반 1:55 | brand from video title; no camera module visible on worn frames |
| [zenni-haul](https://www.youtube.com/watch?v=aextrPG4v-A) | Zenni frames (try-on) | ood | – | 일반 3:02 | brand from video title; no camera module visible on worn frames |
| [zenni-review-try-on](https://www.youtube.com/watch?v=1tb9lrxRjns) | Zenni frames (try-on) | ood | – | 일반 2:01 | brand from video title; no camera module visible on worn frames |

## 파일 형식

세트 하나는 JSON 파일 하나다.
`cases`의 항목 하나는 영상 하나다.
`segments`의 항목 하나는 판정 단위 하나다.

- `label`: `ordinary_glasses`, `camera_glasses`, `no_glasses`, `unknown` 중 하나
- `view`: `frontal`, `three_quarter`, `profile`, `mixed` 중 하나
- `training_overlap`: 학습 데이터의 제품과 어떤 관계인지 적는다.
  - `in_training`: 같은 제품이 학습 데이터에 있다.
  - `same_family`: 같은 제품군의 다른 세대나 모델이 학습 데이터에 있다.
  - `ood`: 학습 데이터에 없는 제품군이다.
  - 정답이 `no_glasses`인 구간은 집계할 때 자동으로 `not_applicable`이 된다.
- `training_product_ids`: `training-products-20261127.json`의 `product_id`다. `in_training`과 `same_family`에는 반드시 적는다.
- `product_evidence`: 제품을 무엇으로 확인했는지 적는다.
- `person_group`: `korean`, `non_korean`, `unknown` 중 하나다.
  - 얼굴을 보고 추정하지 않는다.
  - 자기소개나 한국어 채널처럼 확인할 수 있는 근거가 있을 때만 `korean` 또는 `non_korean`을 적는다.
  - 그 근거를 `person_group_basis`에 적는다. 근거가 없으면 `unknown`으로 둔다.
  - v1의 영상은 모두 `unknown`이다.
- `review.status`: `pending_human_review` 또는 `confirmed`
- 한 구간에는 한 사람이 같은 상태로 나오는 장면만 넣는다.
- 세트 안에서 `id`는 겹치지 않아야 한다.

## 처음 설정하기

1. 저장소를 받는다.

```bash
git clone https://github.com/taehyeon03/ai-glasses-detector.git
cd ai-glasses-detector
```

2. ffmpeg와 Python 패키지를 설치한다.

```bash
sudo apt install ffmpeg
python3 -m venv ~/.local/share/ai-glasses-camera-env
~/.local/share/ai-glasses-camera-env/bin/pip install -r requirements-youtube.txt
```

3. 모델 묶음을 받는다.

모델 묶음은 공개 저장소에 올리지 않는다.
팀 내부에서 폴더째로 전달받아 아래 위치에 둔다.

```
~/.local/share/ai-glasses-models/<모델 이름>/
  manifest.json
  model.onnx
  face_detection_yunet_2023mar.onnx
```

현재 기준 모델은 `mobilenet-crop-s44`다.
`manifest.json`의 `model_sha256`과 `model.onnx`가 맞지 않으면 실행을 멈춘다.
다른 위치에 두었다면 `--models-root`로 지정한다.

## 실행

세트 파일의 형식만 검사한다.

```bash
python -m scripts.youtube_testset --set youtube_test/v1.json --check
```

세트 전체를 판정한다.
CPU에서 약 30분 분량을 2 fps로 처리한다.

```bash
python -m scripts.youtube_testset --set youtube_test/v1.json --model mobilenet-crop-s44
```

일부만 판정할 수 있다.

```bash
python -m scripts.youtube_testset --set youtube_test/v1.json --model mobilenet-crop-s44 --overlap ood
python -m scripts.youtube_testset --set youtube_test/v1.json --model mobilenet-crop-s44 --overlap in_training --overlap same_family
python -m scripts.youtube_testset --set youtube_test/v1.json --model mobilenet-crop-s44 --person-group korean
```

화면으로 보면서 영상 하나씩 시험하려면 웹 화면을 연다.
서버는 이 PC 안에서만 열린다.

```bash
bash scripts/run_youtube_test.sh
```

브라우저에서 `http://127.0.0.1:17890`을 연다.

## 결과 기록

- 실행마다 `~/.local/share/ai-glasses-field-evaluation/youtube/<run_id>/`에 기록이 남는다.
  - `run.json`: 입력과 모델 SHA256과 Git commit과 영상 정보와 구간 결과
  - `run.log`: 실행 로그
  - `frame-predictions.jsonl`: 프레임별 점수
- 전체 이력은 같은 폴더의 `history.jsonl`에 쌓인다.
- 세트 실행의 요약은 `sets/<세트>-<모델>-<시각>/report.md`와 `report.json`이다.
- 요약에는 학습 관계별과 인물 그룹별 오탐률과 재현율이 따로 나온다.
- 공유할 때는 `report.md`와 `report.json`만 `docs/experiments/results/`에 커밋한다.
- 영상과 프레임과 모델 묶음은 커밋하지 않는다.

`in_training`과 `same_family`의 결과를 처음 보는 제품의 성능으로 해석하지 않는다.
온라인 영상의 결과는 실제 착용 평가와 합치지 않는다.
판정 규칙은 구간의 프레임 점수 평균에 모델 묶음의 임계값을 적용하는 것이다.
점수가 나온 프레임이 3개 미만이면 판정 보류로 센다.

## 세트를 늘리는 방법

1. JSON에 영상과 구간을 추가한다.
2. 구간의 모든 초를 확인하고 상태가 바뀌는 초를 뺀다.
3. `--check`로 형식을 검사한다.
4. 사람이 영상을 보고 확인했으면 `review.status`를 `confirmed`로 둔다.
5. 한국인 비교가 필요하면 근거가 있는 한국어 채널의 착용 영상을 추가한다.
