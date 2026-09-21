-- 레시피 DB 초기화 (검사 조건·케이블 정보)
--
--   sqlite3 ~/ros_ws/results/inspection.db < ~/ros_ws/scripts/init_recipe_db.sql
--
-- DB 파일은 .gitignore 로 저장소에서 제외한다(공개 저장소). 그래서 파일을 잃어버렸거나 처음
-- 받았을 때 이 스크립트로 다시 만든다. 검사 결과 테이블(inspection_result, inspection_run)은
-- result_recorder_node 가 첫 결과를 저장할 때 알아서 만들므로 여기에 없다.
--
-- 팀의 실제 레시피 테이블이 정해지면 그 테이블을 아래 컬럼 이름으로 묶는 뷰 v_recipe_point 만
-- 만들면 된다. HMI 쪽 코드는 뷰 하나만 본다 (src/cable_hmi/cable_hmi/recipe_db.py 참고).
--
-- pull_force_limit_n 은 Pull 을 멈추는 힘(안전 상한)이지 합격선이 아니다. 합격 여부는 그때의
-- 변위(max_displacement_mm)로 가른다. 합격 기준 힘은 아직 정해지지 않았다.
--
-- 아래 행은 레시피 JSON(recipe_prototype/recipe/examples/)의 Point 구성에 맞춘 예시값이다.
-- 케이블 번호·종류·제품 ID 는 실제 값으로 바꿔 쓸 것.

CREATE TABLE IF NOT EXISTS recipe_point (
  recipe_id           TEXT NOT NULL,
  recipe_version      TEXT,
  product_id          TEXT,
  point_order         INTEGER,     -- 있으면 이 순서로 정렬한다
  point_id            TEXT NOT NULL,
  point_name          TEXT,
  cable_id            TEXT,
  cable_type          TEXT,
  max_displacement_mm REAL,        -- 허용 변위. 넘으면 FAIL_DISPLACEMENT
  pull_force_limit_n  REAL,        -- Pull 정지 상한 (판정 기준이 아니다)
  repeat_count        INTEGER,
  grip_width_mm       REAL,
  PRIMARY KEY (recipe_id, point_id));

CREATE VIEW IF NOT EXISTS v_recipe_point AS SELECT * FROM recipe_point;

INSERT OR REPLACE INTO recipe_point VALUES
 ('AUTOMOTIVE_CABLE_INSPECTION_EXAMPLE','0.1.0','PANEL-EXAMPLE',1,'BCM_P01','BCM_POWER_CONNECTOR','PWR-1','MOLEX',1.5,5.0,3,25.0),
 ('AUTOMOTIVE_CABLE_INSPECTION_EXAMPLE','0.1.0','PANEL-EXAMPLE',2,'BCM_P02','BCM_CAN_CONNECTOR','CAN-2','MOLEX',1.5,5.0,3,25.0),
 ('AUTOMOTIVE_CABLE_INSPECTION_EXAMPLE','0.1.0','PANEL-EXAMPLE',3,'VCU_P01','VCU_POWER_CONNECTOR','PWR-3','MOLEX',1.5,5.0,3,25.0),
 ('AUTOMOTIVE_CABLE_INSPECTION_EXAMPLE','0.1.0','PANEL-EXAMPLE',4,'VCU_P02','VCU_SIGNAL_CONNECTOR','SIG-4','MOLEX',1.5,5.0,3,25.0),
 ('VIRTUAL_TEST','0.1.0','VIRTUAL-RIG',1,'VT_P01','VIRTUAL_POINT_1','USB-1','USB-A',1.5,5.0,3,22.0),
 ('VIRTUAL_TEST','0.1.0','VIRTUAL-RIG',2,'VT_P02','VIRTUAL_POINT_2','USB-2','USB-A',1.5,5.0,3,22.0),
 ('VIRTUAL_TEST','0.1.0','VIRTUAL-RIG',3,'VT_P03','VIRTUAL_POINT_3','USB-3','USB-A',1.5,5.0,3,22.0);
