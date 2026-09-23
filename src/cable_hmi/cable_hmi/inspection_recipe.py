"""
검사 레시피 v0.1 (JSON) 을 읽어 검사 시작 서비스에 실을 메시지로 바꾼다.

형식은 cable_inspection/recipe/inspection/*.json 과 같다 (2026-09-23 기준):

    {"recipe_id": "...", "recipe_version": "...", "coordinate_frame": "BASE",
     "connector_type": "...", "execution_order": ["P1", "P2"],
     "points": {"P1": {"point_id": "P1", "point_name": "...", "enabled": true,
                       "ready_pose": {"task": [6개], "joint": [6개]}, "entry_pose": {...},
                       "entry_setting": {...}, "grip_setting": {...}, "pull_setting": {...}}}}

검사 PC 의 코드(cable_inspection)는 import 하지 않는다 - HMI PC 에는 cable_interfaces 와
cable_hmi 만 있으면 된다. 여기서 하는 검사는 보내기 전에 흔한 실수를 화면에 알리려는 것이고,
최종 판단은 Main 이 한다(같은 규칙: inspection_recipe.from_message / validate_recipe).

단위는 두산 기준이다: task = [mm, mm, mm, deg, deg, deg] (BASE, ZYZ), joint = [deg x 6].
"""

from dataclasses import dataclass, field
import json
import math
from pathlib import Path
from typing import Any, Dict, List, Tuple

from cable_interfaces.msg import (
    EntrySetting, GripSetting, InspectionPoint, InspectionPose, InspectionRecipe, PullSetting,
)

# 메시지 그룹별로 반드시 있어야 하는 양수 값. 메시지 필드 이름과 같다.
SETTINGS = {
    'entry_setting': (EntrySetting, ('max_distance_mm', 'force_guard_n', 'timeout_s')),
    'grip_setting': (GripSetting, ('soft_close_width_mm', 'soft_open_width_mm', 'hard_width_mm',
                                   'soft_force_n', 'hard_force_n')),
    'pull_setting': (PullSetting, ('force_limit_n', 'max_distance_mm', 'timeout_s', 'speed_mm_s',
                                   'normal_displacement_limit_mm')),
}
ENTRY_MAX_DISTANCE_MM = 25.0
MAX_POINTS = 1000
MAX_TEXT = 256


@dataclass
class RecipeFile:
    """레시피 파일 1개. data 는 검사를 통과한 JSON 원본이다."""

    recipe_id: str
    recipe_version: str
    path: str
    data: Dict[str, Any] = field(repr=False, default_factory=dict)

    @property
    def point_count(self) -> int:
        return len(self.data['execution_order'])

    @property
    def enabled_count(self) -> int:
        return sum(1 for p in self.data['points'].values() if p['enabled'])


def _text(value, name: str) -> str:
    if not isinstance(value, str) or not value.strip() or len(value) > MAX_TEXT:
        raise ValueError(f'{name}: 1~{MAX_TEXT}자 문자열이어야 합니다')
    return value


def _positive(value, name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)) \
            or not math.isfinite(value) or value <= 0:
        raise ValueError(f'{name}: 양수여야 합니다 (지금 {value!r})')
    return float(value)


def _pose(raw, name: str) -> Dict[str, List[float]]:
    if not isinstance(raw, dict):
        raise ValueError(f'{name}: task / joint 를 가진 객체여야 합니다')
    for key in ('task', 'joint'):
        values = raw.get(key)
        if not isinstance(values, list) or len(values) != 6 or not all(
                not isinstance(v, bool) and isinstance(v, (int, float)) and math.isfinite(v)
                for v in values):
            raise ValueError(f'{name}.{key}: 숫자 6개여야 합니다')
    return raw


def _check_point(key: str, raw) -> None:
    if not isinstance(raw, dict):
        raise ValueError(f'{key}: 포인트는 객체여야 합니다')
    if raw.get('point_id') != key:
        raise ValueError(f'{key}: points 의 키와 point_id 가 다릅니다')
    _text(key, 'point_id')
    if not isinstance(raw.get('point_name', ''), str) or len(raw.get('point_name', '')) > MAX_TEXT:
        raise ValueError(f'{key}: point_name 이 유효하지 않습니다')
    if type(raw.get('enabled')) is not bool:
        raise ValueError(f'{key}: enabled 는 true / false 여야 합니다')
    _pose(raw.get('ready_pose'), f'{key}: ready_pose')
    _pose(raw.get('entry_pose'), f'{key}: entry_pose')
    for group, (_msg, names) in SETTINGS.items():
        values = raw.get(group)
        if not isinstance(values, dict):
            raise ValueError(f'{key}: {group} 가 없습니다')
        for name in names:
            _positive(values.get(name), f'{key}: {group}.{name}')
    if raw['entry_setting']['max_distance_mm'] > ENTRY_MAX_DISTANCE_MM:
        raise ValueError(f'{key}: Entry 최대거리는 {ENTRY_MAX_DISTANCE_MM:g} mm 이하여야 합니다')


def check(data) -> Dict[str, Any]:
    """레시피 JSON(dict)을 검사한다. 틀리면 ValueError (이유 포함)."""
    if not isinstance(data, dict):
        raise ValueError('JSON 최상위 값은 객체여야 합니다')
    for name in ('recipe_id', 'recipe_version', 'connector_type'):
        _text(data.get(name), name)
    if data.get('coordinate_frame') != 'BASE':
        raise ValueError('coordinate_frame 은 BASE 여야 합니다')
    points, order = data.get('points'), data.get('execution_order')
    if not isinstance(points, dict) or not 1 <= len(points) <= MAX_POINTS:
        raise ValueError(f'points 는 point_id 를 키로 갖는 객체(1~{MAX_POINTS}개)여야 합니다')
    if not isinstance(order, list) or len(order) != len(set(order)):
        raise ValueError('execution_order 는 중복 없는 Point 목록이어야 합니다')
    if set(order) != set(points):
        raise ValueError('모든 Point 가 execution_order 에 한 번씩 있어야 합니다 '
                         '(제외할 Point 는 enabled=false)')
    for key, raw in points.items():
        _check_point(key, raw)
    return data


def load(path) -> RecipeFile:
    """레시피 JSON 하나를 읽고 검사한다. 틀리면 ValueError (이유 포함)."""
    path = Path(path)
    try:
        data = json.loads(path.read_text(encoding='utf-8'))
    except (OSError, ValueError) as e:
        raise ValueError(f'읽을 수 없음 ({e})') from None
    check(data)
    return RecipeFile(data['recipe_id'], data['recipe_version'], str(path), data)


def scan(directory) -> Tuple[Dict[str, RecipeFile], List[str]]:
    """
    폴더의 *.json 을 모두 읽는다 (*.template.json 은 틀이라 건너뛴다).

    ({recipe_id: RecipeFile}, [문제 설명]) 을 돌려준다. 잘못된 파일 하나 때문에 나머지가
    안 읽히지 않도록, 읽지 못한 파일은 건너뛰고 문제 목록에 이유를 남긴다.
    """
    recipes: Dict[str, RecipeFile] = {}
    problems: List[str] = []
    folder = Path(directory).expanduser()
    if not folder.is_dir():
        return recipes, [f'레시피 폴더가 없습니다: {folder}']
    for path in sorted(folder.glob('*.json')):
        if path.name.endswith('.template.json'):
            continue
        try:
            info = load(path)
        except ValueError as e:
            problems.append(f'{path.name}: {e}')
            continue
        if info.recipe_id in recipes:
            problems.append(f'{path.name}: recipe_id {info.recipe_id} 가 '
                            f'{Path(recipes[info.recipe_id].path).name} 과 중복 - 건너뜀')
            continue
        recipes[info.recipe_id] = info
    return recipes, problems


def signature(directory) -> tuple:
    """폴더 내용이 바뀌었는지 비교할 값 (파일 이름과 수정 시각)."""
    folder = Path(directory).expanduser()
    if not folder.is_dir():
        return ()
    return tuple(sorted((p.name, p.stat().st_mtime_ns) for p in folder.glob('*.json')))


def to_message(data) -> InspectionRecipe:
    """검사를 통과한 레시피 JSON 을 메시지로. points 배열 순서 = execution_order = 실행 순서."""
    check(data)
    msg = InspectionRecipe(
        recipe_id=data['recipe_id'], recipe_version=data['recipe_version'],
        coordinate_frame=data['coordinate_frame'], connector_type=data['connector_type'])
    for point_id in data['execution_order']:
        raw = data['points'][point_id]
        point = InspectionPoint(point_id=point_id, point_name=raw.get('point_name', ''),
                                enabled=raw['enabled'])
        for pose in ('ready_pose', 'entry_pose'):
            setattr(point, pose, InspectionPose(
                task=[float(v) for v in raw[pose]['task']],
                joint=[float(v) for v in raw[pose]['joint']]))
        for group, (msg_type, names) in SETTINGS.items():
            setattr(point, group, msg_type(**{n: float(raw[group][n]) for n in names}))
        msg.points.append(point)
    return msg
