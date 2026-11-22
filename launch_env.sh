#!/usr/bin/env bash

export OMP_NUM_THREADS=1
export MKL_NUM_THREADS=1
export NUMEXPR_NUM_THREADS=1
export OPENBLAS_NUM_THREADS=1
export VECLIB_MAXIMUM_THREADS=1

# models get lower priority than ui
# - ui is ~5ms
# - modeld is 20ms
# - DM is 10ms
# in order to run ui at 60fps (16.67ms), we need to allow
# it to preempt the model workloads. we have enough
# headroom for this until ui is moved to the CPU.
export QCOM_PRIORITY=12

if [ -z "$AGNOS_VERSION" ]; then
  export AGNOS_VERSION="20.6"
fi

export STAGING_ROOT="/data/safe_staging"

# 준파일럿: 차종 고정 (PV5는 아직 펌웨어 지문이 없어 자동 인식이 안 됨)
# - /data/junpilot_car 파일에 차종 코드를 적으면 그 값을 사용 (예: KIA_PV5)
# - 파일 내용이 auto 이면 공식 자동 인식 사용
# - 파일이 없으면 KIA_PV5로 고정
# 펌웨어 조회는 그대로 실행되므로 로그에 PV5 펌웨어 버전이 기록된다.
if [ -z "$FINGERPRINT" ]; then
  JUNPILOT_CAR="KIA_PV5"
  if [ -f /data/junpilot_car ]; then
    JUNPILOT_CAR="$(tr -d '[:space:]' < /data/junpilot_car)"
  fi
  if [ "$JUNPILOT_CAR" != "auto" ] && [ -n "$JUNPILOT_CAR" ]; then
    export FINGERPRINT="$JUNPILOT_CAR"
  fi
fi
