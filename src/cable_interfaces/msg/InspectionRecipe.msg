# HMI에서 검사 측으로 식별자·버전과 실행 순서별 포인트를 포함한 전체 검사 레시피를 전달한다.
string recipe_id
string recipe_version
string coordinate_frame
string connector_type
# Array order is execution order, disabled points are skipped.
InspectionPoint[] points
