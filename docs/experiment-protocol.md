# 실험 공통 규약

AGENTS.md는 모든 브랜치에 적용한다.
실행 환경은 PC에 마련한다.
Nano에서는 최종 추론을 시험한다.

## 실행 기록

`runs/<run_id>/provenance.json`에는 실행 조건을 저장한다.
`metrics.jsonl`에는 split과 epoch와 step을 구분해서 저장한다.
학습과 검증은 매 epoch 평가한다.
테스트는 선택된 모델로 한 번 평가한다.
각 평가에는 loss와 accuracy와 macro_f1과 confusion_matrix가 있어야 한다.
일반 안경의 false_positive_rate와 카메라 안경의 camera_recall도 기록한다.
`steps.jsonl`에는 최적화 중의 loss를 기록한다.
`weight_norms.jsonl`에는 레이어마다 L2 norm과 RMS를 기록한다.
`summary.json`에는 최종 평가와 선택 근거를 저장한다.
`status.json`에는 completed 또는 failed를 저장한다.
`pip-freeze.txt`에는 실제 패키지 버전을 저장한다.
`checkpoint.pt`에는 선택된 분류기와 backbone 출처를 저장한다.
대용량 파일과 얼굴이 포함된 그림은 SSD에 보관한다.
공개 Git에는 수치와 실험 설명만 보관한다.
동결한 encoder의 특징으로 분류기를 학습하는 공통 실행기는 `pipeline/probe.py`에 있다.
동결한 encoder의 attention은 분류기 학습으로 변하지 않는다.
분류 점수에 대한 설명은 별도 분석으로 추가한다.
설정의 `explain`을 사용하려면 해당 브랜치에 `pipeline/explain.py`가 있어야 한다.

## 발표를 위한 실험 문서

각 브랜치의 `docs/experiments/<experiment_id>.md`에 가설을 작성한다.
사용한 데이터를 revision으로 고정한다.
변경한 조건을 설명한다.
비교할 때 고정한 조건을 설명한다.
관측 결과와 해석을 구분한다.
모델을 다시 선택하면 새로운 실행으로 기록한다.
실패 사례도 보존한다.

## 최종 보드 검증

`jetson_validation`은 실측 전까지 pending이다.
보드에서 `/etc/nv_tegra_release`를 저장한다.
`dpkg-query -W nvidia-jetpack libnvinfer8`로 설치 버전을 기록한다.
`nvpmodel -q`로 전력 모드를 기록한다.
Nano에서 TensorRT 엔진을 빌드한다.
학습 모델과 엔진의 출력 차이를 같은 입력으로 비교한다.
전처리를 포함하는 지연을 측정한다.
CSI 카메라부터 판정까지의 지연도 측정한다.
`tegrastats`로 전체 메모리와 온도를 저장한다.
30분 동안 동작한 결과를 기록한다.
현재 소프트웨어만으로 보드 성공을 판정하지 않는다.
