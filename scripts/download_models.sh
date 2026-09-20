#!/usr/bin/env bash
# FACE_PROVIDER=local 이 쓰는 사전학습 모델 파일을 받는다.
#
# 이 파일들은 이미 backend/models/ 에 커밋되어 있으므로 평소에는 이 스크립트를
# 실행할 필요가 없다. git 없이 새로 받아야 하거나 파일이 깨졌을 때만 쓴다.
#
#   face_detection_yunet_2023mar.onnx    ~230KB  (OpenCV Zoo, 얼굴 탐지)
#   face_recognition_sface_2021dec.onnx  ~37MB   (OpenCV Zoo, 얼굴 임베딩)
#   haarcascade_eye.xml                  ~340KB  (OpenCV, 눈 검출)

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
MODELS_DIR="$SCRIPT_DIR/../backend/models"
mkdir -p "$MODELS_DIR"

download() {
  local url="$1" dest="$2"
  echo "받는 중: $dest"
  curl -sL --fail --max-time 120 -o "$dest" "$url"
}

# opencv_zoo는 큰 모델 파일을 git-lfs로 관리한다. raw.githubusercontent.com은
# LFS 포인터 텍스트만 주므로 media.githubusercontent.com에서 실제 바이너리를 받는다.
download \
  "https://media.githubusercontent.com/media/opencv/opencv_zoo/main/models/face_detection_yunet/face_detection_yunet_2023mar.onnx" \
  "$MODELS_DIR/face_detection_yunet_2023mar.onnx"

download \
  "https://media.githubusercontent.com/media/opencv/opencv_zoo/main/models/face_recognition_sface/face_recognition_sface_2021dec.onnx" \
  "$MODELS_DIR/face_recognition_sface_2021dec.onnx"

download \
  "https://raw.githubusercontent.com/opencv/opencv/4.x/data/haarcascades/haarcascade_eye.xml" \
  "$MODELS_DIR/haarcascade_eye.xml"

echo "완료. backend/models/ 확인:"
ls -la "$MODELS_DIR"
