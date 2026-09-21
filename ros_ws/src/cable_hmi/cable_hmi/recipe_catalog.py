"""
검사포인트 레시피(JSON) 목록을 읽는다.

레시피 파일 형식은 recipe_prototype 의 InspectionRecipe.save_json() 이 만드는 JSON 이다:

    {"recipe_id": "...", "recipe_version": "...",
     "points": {"BCM_P01": {"point_id": "BCM_P01", "point_name": "...",
                            "task": [6개], "joint": [6개], "coordinate_frame": "BASE"}, ...}}

프로토타입의 파이썬 코드를 import 하지 않고 JSON 만 읽는다 - 그 코드는 ROS 패키지가 아니라
위치가 바뀔 수 있고, HMI 쪽에 필요한 것은 목록·버전·포인트 이름뿐이기 때문이다.
모르는 필드는 무시하므로 나중에 포인트에 검사 조건 필드가 추가돼도 그대로 읽힌다.

단위는 두산 기준이다: task = [mm, mm, mm, deg, deg, deg] (BASE, ZYZ), joint = [deg x 6].
"""

from dataclasses import dataclass, field
import json
import math
from pathlib import Path
from typing import Dict, List, Tuple


@dataclass
class RecipePoint:
    """검사포인트 1개."""

    point_id: str
    point_name: str = ''
    task: List[float] = field(default_factory=list)
    joint: List[float] = field(default_factory=list)

    @property
    def taught(self) -> bool:
        """
        실제로 티칭된 좌표인가.

        예제 파일처럼 task·joint 가 전부 0 이면 자리표시자다. 그대로 로봇에 보내면 팔을
        곧게 편 기계 원점으로 가므로, 이동에 쓰기 전에 반드시 이 값을 확인해야 한다.
        """
        return any(v != 0.0 for v in self.task) and any(v != 0.0 for v in self.joint)


@dataclass
class RecipeInfo:
    """레시피 파일 1개에서 읽은 내용."""

    recipe_id: str
    recipe_version: str
    points: List[RecipePoint]
    path: str = ''

    @property
    def untaught_points(self) -> List[str]:
        """좌표가 자리표시자(전부 0)인 포인트의 id."""
        return [p.point_id for p in self.points if not p.taught]


def _pose(raw, name: str, point_id: str) -> List[float]:
    if not isinstance(raw, list) or len(raw) != 6:
        raise ValueError(f'{point_id}: {name} 좌표는 숫자 6개여야 합니다')
    try:
        values = [float(v) for v in raw]
    except (TypeError, ValueError):
        raise ValueError(f'{point_id}: {name} 좌표에 숫자가 아닌 값이 있습니다') from None
    if not all(math.isfinite(v) for v in values):
        raise ValueError(f'{point_id}: {name} 좌표에 유효하지 않은 숫자가 있습니다')
    return values


def load_recipe_file(path) -> RecipeInfo:
    """레시피 JSON 하나를 읽는다. 형식이 틀리면 ValueError (이유 포함)."""
    path = Path(path)
    try:
        data = json.loads(path.read_text(encoding='utf-8'))
    except (OSError, ValueError) as e:
        raise ValueError(f'읽을 수 없음 ({e})') from None
    if not isinstance(data, dict):
        raise ValueError('JSON 최상위 값은 객체여야 합니다')

    recipe_id = str(data.get('recipe_id', '')).strip()
    version = str(data.get('recipe_version', '')).strip()
    raw_points = data.get('points')
    if not recipe_id:
        raise ValueError('recipe_id 가 없습니다')
    if not isinstance(raw_points, dict) or not raw_points:
        raise ValueError('points 는 point_id 를 키로 갖는 비어 있지 않은 객체여야 합니다')

    points = []
    for key, raw in raw_points.items():          # JSON 에 적힌 순서 = 검사 순서
        if not isinstance(raw, dict):
            raise ValueError(f'{key}: 포인트는 객체여야 합니다')
        points.append(RecipePoint(
            point_id=str(key),
            point_name=str(raw.get('point_name', '')),
            task=_pose(raw.get('task'), 'task', key),
            joint=_pose(raw.get('joint'), 'joint', key)))
    return RecipeInfo(recipe_id, version, points, str(path))


def scan(directory) -> Tuple[Dict[str, RecipeInfo], List[str]]:
    """
    폴더의 *.json 을 모두 읽는다.

    ({recipe_id: RecipeInfo}, [문제 설명]) 을 돌려준다. 잘못된 파일 하나 때문에 나머지가
    안 읽히지 않도록, 읽지 못한 파일은 건너뛰고 문제 목록에 이유를 남긴다.
    """
    recipes: Dict[str, RecipeInfo] = {}
    problems: List[str] = []
    folder = Path(directory).expanduser()
    if not folder.is_dir():
        return recipes, [f'레시피 폴더가 없습니다: {folder}']
    for path in sorted(folder.glob('*.json')):
        try:
            info = load_recipe_file(path)
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
