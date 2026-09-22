# Point 결과. Pull 중 실측 폭 16 mm 미만은 파지 실패다.
string PASS=PASS
string FAIL=FAIL
string SYSTEM_ERROR=SYSTEM_ERROR

# 검사 실행 및 포인트 식별
int64 run_id
string stamp
string recipe_id
string recipe_version
string point_id
string point_name
string cable_type

# 판정 및 처리 상태
string result
string reason_code
string reason
string termination_reason
string judgment_status
string sequence_status

# Pull 측정값과 해당 레시피 기준 (N, mm)
float64 max_force_n
float64 required_pull_force_n
float64 displacement_mm
float64 displacement_limit_mm

# 원시 기록 식별자, Entry 좌표 (BASE mm/deg, joint deg)
string force_data_id
float64[] task
float64[] joint
bool db_saved

# Soft 종료 기준 폭, Pull 전체(정지 대기 포함) 최소 실측 폭 (mm)
float64 soft_width_mm
float64 pull_width_mm
# 부호 있는 차이: Pull 최소 폭 - Soft 기준 폭 (mm). 차이는 기록용이다.
float64 width_delta_mm
float64 grip_failure_width_mm
