"""HMI 명령·레시피 입력과 상태·결과 출력을 처리한다.
통신 형식을 검사하고 실행 요청은 Main, 레시피 해석은 Recipe에 전달한다.
ROS 연결 생성은 HmiNode가 담당한다.
"""

import json
import math
import time
from datetime import datetime
from std_msgs.msg import String
from cable_inspection.sequence.main.data_models.system_state import SystemState


STATE_NAMES = {
    0: "INITIALIZING", 1: "STANDBY", 2: "MOVING", 3: "SAFE_OFF",
    4: "TEACHING", 5: "SAFE_STOP", 6: "EMERGENCY_STOP", 7: "HOMMING",
    8: "RECOVERY", 9: "SAFE_STOP2", 10: "SAFE_OFF2", 15: "NOT_READY",
}



class HmiInterface:
    """기존 HMI 통신 계약을 유지하는 요청·응답 처리 component."""



    # 기능: 최근 Heartbeat가 통신 제한시간 안에 도착했는지 확인한다.
    #     반환: 연결이 유효하면 True, 미수신 또는 만료이면 False.
    def is_connected(self):
        return (self.last_heartbeat is not None
                and time.monotonic() - self.last_heartbeat <= self.heartbeat_timeout_s)



    # 기능: Heartbeat 시각을 갱신하고 Main에 통신 복구를 알린다.
    #     _message: HMI 또는 터미널에서 받은 Empty 메시지.
    #     반환: 없음. 통신 복구가 자동 RESUME을 실행하지는 않는다.
    def receive_heartbeat(self, _message):
        self.last_heartbeat = time.monotonic()

        if self.communication_lost_handled:
            self.main.controller.communication_recovered()
            self.publish_log("INFO", "통신 복구. 상태를 다시 전달하며 RESUME을 기다립니다.")

        self.communication_lost_handled = False



    # 기능: 통신 유실을 Main에 알리고 작업 상태를 주기적으로 발행한다.
    #     반환: 없음. 작업 중 Heartbeat 유실은 한 번만 알린다.
    def update_communication(self):
        active = self.main.controller.state in {SystemState.RUNNING, SystemState.PAUSE_REQUEST, SystemState.PAUSED}

        if active and not self.is_connected() and not self.communication_lost_handled:
            self.communication_lost_handled = True
            self.main.controller.communication_lost()
            self.publish_log("WARN", f"{self.control_mode.upper()} COMM LOST: Safe Pause 요청")

        self.publish_status(force=False)



    # 기능: Main·Recipe의 현황과 최신 검사 측정값을 기존 상태 계약으로 발행한다.
    #     force: True이면 대기 중 내용이 같아도 발행한다.
    #     반환: 없음. 작업 중에는 매 호출 시, 대기 중에는 변경 시 발행한다.
    def publish_status(self, force=True):
        context, backend = self.main.controller.context, self.main.controller.backend
        progress = self.main.controller.recipes.progress(
            self.main.controller.run_id if self.main.operation != "HOME" else 0)
        total = progress["total_points"]
        state = self.main.controller.state.value
        status = {
            "schema_version": 1,
            "operation": self.main.operation,
            "request_id": getattr(self, "_request_id", ""),
            "state": "IDLE" if state == "SYSTEM_READY" else state,
            "run_state": state, "alarm": self.main.controller.last_error,
            "control_mode": self.control_mode, "control_connected": self.is_connected(),
            "available_recipes": self.main.controller.recipes.available_ids(), "run_id": self.main.controller.run_id,
            "recipe_id": context.recipe_id if context else self.main.selected_recipe,
            "selected_recipe_id": self.main.selected_recipe,
            "job_id": context.job_id if context else "",
            "recipe_version": progress["recipe_version"],
            "execution_index": progress["execution_index"],
            "resume_point": context.resume_point if context else "",
            "total_points": total, "current_point": progress["current_point"],
            "current_step": context.current_sequence if context else "",
            "pending_judgments": progress["pending_judgments"],
            "progress_percent": progress["progress_percent"],
            "job_summary": self.main.controller.last_summary,
        }
        active = state in {"RUNNING", "PAUSE_REQUEST", "PAUSED"} or (
            self.main.worker is not None and self.main.worker.is_alive())
        status["work_active"] = active
        status["criteria"] = {}
        status["measurement"] = None

        if context and progress["current_point"]:
            point = progress["point"]

            if point:
                pull, grip = point["pull_setting"], point["grip_setting"]
                status["criteria"] = {
                    "required_pull_force_n": pull["force_limit_n"],
                    "max_displacement_mm": pull["normal_displacement_limit_mm"],
                    "pull_max_distance_mm": pull["max_distance_mm"],
                    "grip_width_mm": grip["hard_width_mm"],
                }

            sample = getattr(backend, "latest_sample", None)

            if active and sample and sample.get("point_id") == progress["current_point"]:
                age = max(0.0, time.monotonic() - sample["monotonic_s"])
                status["measurement"] = {
                    "sample_stamp": sample["timestamp"], "age_s": age,
                    "valid": age <= 2.0,
                    "phase": sample["phase"],
                    "measurement_kind": sample["measurement_kind"],
                    "pull_force_n": sample["pull_force_n"],
                    "pull_displacement_mm": sample["pull_displacement_mm"],
                }

        # 대기는 변경 시/SYNC에만 전송, 작업 중에는 10 Hz. 최종 상태는 보존한다.
        payload = json.dumps(status, ensure_ascii=False, allow_nan=False)

        if force or active or payload != self._last_status:
            status["stamp"] = datetime.now().astimezone().isoformat(timespec="milliseconds")
            self.status_pub.publish(String(data=json.dumps(status, ensure_ascii=False, allow_nan=False)))
            self._last_status = payload



    # 기능: 동일한 로그를 터미널과 HMI 로그 토픽에 전달한다.
    #     level: INFO/WARN/ERROR 로그 수준.
    #     text: 전달할 로그 본문.
    #     반환: 없음. ERROR는 기존 popup=True를 유지한다.
    def publish_log(self, level, text):
        print(f"[{level}] {text}", flush=True)
        self.log_pub.publish(String(data=json.dumps({"level": level, "text": text,
                                                    "popup": level == "ERROR"}, ensure_ascii=False)))



    # 기능: 실행 ID별로 고정된 검사 레시피를 한 번 발행한다.
    #     run_id: 검사 실행 식별자.
    #     recipe: 이번 실행에 고정된 레시피 사전.
    #     반환: 없음. 같은 run_id를 재전달해도 중복 발행하지 않는다.
    def publish_execution_snapshot(self, run_id, recipe):
        if run_id in self._published_snapshots:
            return

        payload = {"run_id": run_id, "request_id": self._request_id,
                   "recipe_id": recipe["recipe_id"], "recipe_version": recipe["recipe_version"],
                   "recipe": recipe}
        self.snapshot_pub.publish(String(data=json.dumps(payload, ensure_ascii=False, allow_nan=False)))
        self._published_snapshots.add(run_id)



    # 기능: 명령 JSON을 검증하고 실행 요청을 Main에 전달한다.
    #     message: name·args를 담은 String 메시지.
    #     반환: 없음. 잘못된 명령은 로그로 알리며 실행하지 않는다.
    def receive_command(self, message):
        try:
            raw = json.loads(message.data)

            if not isinstance(raw, dict) or not isinstance(raw.get("args", {}), dict):
                raise ValueError("명령은 name과 args를 가진 JSON 객체여야 합니다.")

            name, args = str(raw.get("name", "")).upper(), raw.get("args", {})

            if name == "START" and self.control_mode == "hmi":
                raise ValueError("HMI START는 /cable_inspection/start 서비스로 검사 레시피 전체를 전달하세요.")

            if name != "SYNC":
                if name in {"HOME_RETURN", "MOVE_HOME"} and not self.main.is_running():
                    self._request_id = ""

                self.main.execute_command(name, args)

            self.publish_status()

        except (ValueError, TypeError, KeyError) as error:
            self.publish_log("ERROR", str(error))



    # 기능: 레시피 수신·요청 중복을 확인하고 Main의 실행 접수 결과를 응답한다.
    #     request: request_id와 전체 Recipe를 담은 StartInspection 요청.
    #     response: accepted·code·message·run_id를 채울 응답 객체.
    #     반환: 접수 또는 거절 정보를 채운 StartInspection 응답. 중복 요청은 재실행하지 않는다.
    def receive_inspection_start(self, request, response):
        rejection_code = "INVALID_REQUEST_ID"

        try:
            if not request.request_id.strip() or len(request.request_id) > 128:
                raise ValueError("request_id는 1~128자여야 합니다.")

            rejection_code = "INVALID_RECIPE"
            recipe = self.main.controller.recipes.decode_message(request.recipe)
            payload = json.dumps(recipe, sort_keys=True, ensure_ascii=False, allow_nan=False)
            previous = self._start_requests.get(request.request_id)

            if previous:
                if previous[0] != payload:
                    rejection_code = "REQUEST_ID_CONFLICT"
                    raise ValueError("동일 request_id에 다른 레시피를 보낼 수 없습니다.")

                response.accepted, response.code, response.run_id = True, "ALREADY_ACCEPTED", previous[1]
                response.message = "이미 접수한 요청입니다. work_status로 실행 결과를 확인하세요."

                return response

            if self.control_mode != "hmi":
                rejection_code = "CONTROL_MODE_MISMATCH"
                raise ValueError("HMI 제어 모드가 아닙니다.")

            if not self.is_connected():
                rejection_code = "HEARTBEAT_MISSING"
                raise ValueError("HMI Heartbeat가 유효하지 않습니다.")

            run_id = time.time_ns() // 1000
            previous_id, self._request_id = self._request_id, request.request_id

            try:
                result = self.main.start_inspection(recipe, run_id)

            except Exception:
                self._request_id = previous_id
                raise

            if not result.success:
                self._request_id = previous_id
                rejection_code = result.code
                raise ValueError(result.message)

            self._start_requests[request.request_id] = (payload, run_id)
            response.accepted, response.code, response.run_id = True, "ACCEPTED", run_id
            response.message = "접수 완료. 장비 초기화 및 실행 결과는 work_status/log로 확인하세요."

        except (ValueError, TypeError, KeyError, AttributeError) as error:
            response.accepted, response.code, response.message = False, rejection_code, str(error)
            response.run_id = 0

        return response



    # 기능: 외부 판정 요청을 판정 담당의 입력 검증·Queue 처리에 전달한다.
    #     message: 검사 측정 정보를 JSON으로 담은 String 메시지.
    #     반환: 없음. 이 콜백에서는 판정 계산을 실행하지 않는다.
    def receive_judgment_request(self, message):
        self.judgment.receive_request(message.data)



    # 기능: 장비별 캐시를 기존 HMI 로봇 상태 형식으로 조합한다. ROS 조회는 하지 않는다.
    #     now: monotonic 시각(s). 생략하면 현재 시각.
    #     반환: 기존 robot_status 스키마의 사전. 장비가 판정한 만료·오류 정보를 보존한다.
    def robot_status_snapshot(self, now=None):
        now = time.monotonic() if now is None else now
        backend = self.main.controller.backend
        fields = {**backend.robot.status_snapshot(now), **backend.gripper.status_snapshot(now)}
        values = {key: entry["value"] for key, entry in fields.items()}
        validity = {key: entry["valid"] for key, entry in fields.items()}
        ages = {key: entry["age_s"] for key, entry in fields.items()}
        errors = {key: entry["error"] for key, entry in fields.items() if not entry["valid"]}
        code, motion = values["robot_state_code"], values["motion_status"]
        wrench = values["wrench_base"]
        robot_motion = ""

        if motion is not None and motion >= 0:
            robot_motion = "MOVING" if motion != 0 else STATE_NAMES.get(code, "")

        return {
            "schema_version": 1,
            "stamp": datetime.now().astimezone().isoformat(timespec="milliseconds"),
            "robot_connected": validity["robot_state_code"],
            "gripper_connected": validity["gripper_width_mm"],
            "task": values["task"], "joint": values["joint"],
            "wrench_base": wrench, "force_norm_n": math.hypot(*wrench[:3]) if wrench else None,
            "gripper_width_mm": values["gripper_width_mm"],
            "robot_state_code": code, "motion_status": motion, "robot_motion": robot_motion,
            "servo": ("OFF" if code in {0, 3, 6, 10, 15} else "ON") if code in STATE_NAMES else "",
            "servo_source": "robot_state_inference",
            "tool": {"name": values["tool_name"], "tcp": values["tcp_name"]},
            "validity": validity, "age_s": ages, "errors": errors,
        }



    # 기능: 장비 상태를 기존 외부 토픽으로 주기 발행한다.
    #     인자: 없음.
    #     반환: 없음. 장비 조회·모션·응답 대기를 실행하지 않는다.
    def publish_robot_status(self):
        self.robot_status_pub.publish(String(data=json.dumps(
            self.robot_status_snapshot(), ensure_ascii=False, allow_nan=False)))
