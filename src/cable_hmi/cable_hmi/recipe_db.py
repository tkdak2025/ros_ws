"""
레시피 정보(케이블, 판정 기준)를 SQLite 에서 읽는다. 읽기 전용.

테이블 구조는 아직 정해지지 않았다. 그래서 이 모듈은 실제 테이블을 모르고, 약속된 뷰
하나만 조회한다:

    v_recipe_point   (포인트 1개 = 1행)

    필수 컬럼   recipe_id, point_id
    선택 컬럼   recipe_version, product_id, point_name, cable_id, cable_type,
                max_displacement_mm, pull_force_n, repeat_count, grip_width_mm, point_order

나중에 테이블을 설계하는 쪽에서 자기 테이블을 위 컬럼 이름으로 묶는 뷰만 만들면, 이 파일을
고치지 않아도 값이 채워진다. 테이블을 쪼개거나 이름을 바꿔도 뷰만 고치면 된다.
선택 컬럼은 없어도 된다(해당 값은 기본값). point_order 가 있으면 그 순서로 정렬한다.

DB 파일이 없거나 뷰가 아직 없는 것은 정상적인 상황이다. 그때는 RecipeDbError 를 던지고,
부르는 쪽은 경고만 남긴 채 DB 없이 계속 동작해야 한다.

이 모듈은 ROS 와 Qt 에 의존하지 않는다. HMI 화면 프로세스에서는 부르지 않는다 -
status / result 를 보내는 노드가 읽어서 메시지에 채워 보낸다(판정에 쓴 기준과 화면에
보이는 기준이 항상 같도록).
"""

from dataclasses import dataclass, field
from pathlib import Path
import sqlite3
from typing import Dict, List

VIEW = 'v_recipe_point'
REQUIRED_COLUMNS = ('recipe_id', 'point_id')
TIMEOUT_SEC = 0.5        # DB 가 잠겨 있어도 노드가 오래 멈추지 않게


class RecipeDbError(Exception):
    """DB 에서 레시피 정보를 읽지 못함. 메시지는 그대로 로그에 쓸 수 있는 이유다."""


@dataclass
class PointInfo:
    """포인트 1개의 레시피 정보."""

    point_id: str
    point_name: str = ''
    cable_id: str = ''
    cable_type: str = ''
    max_displacement_mm: float = 0.0
    pull_force_n: float = 0.0
    repeat_count: int = 0
    grip_width_mm: float = 0.0


@dataclass
class RecipeDbInfo:
    """Recipe 1개의 레시피 정보."""

    recipe_id: str
    recipe_version: str = ''
    product_id: str = ''
    points: Dict[str, PointInfo] = field(default_factory=dict)   # 검사 순서대로


def _text(row, keys, name) -> str:
    return str(row[name]) if name in keys and row[name] is not None else ''


def _number(row, keys, name, kind):
    if name not in keys or row[name] is None:
        return kind()
    try:
        return kind(row[name])
    except (TypeError, ValueError):
        raise RecipeDbError(
            f'{VIEW}.{name} 값이 숫자가 아닙니다: {row[name]!r} '
            f'(recipe {row["recipe_id"]}, point {row["point_id"]})') from None


class RecipeDb:
    """SQLite 파일 하나에 대한 읽기 전용 창구. 호출할 때마다 열고 닫는다."""

    def __init__(self, path):
        self.path = Path(path).expanduser()

    def _connect(self):
        if not self.path.is_file():
            raise RecipeDbError(f'DB 파일이 없습니다: {self.path}')
        try:
            # mode=ro: 이 모듈이 DB 를 만들거나 고칠 일이 없게 한다.
            connection = sqlite3.connect(
                f'file:{self.path}?mode=ro', uri=True, timeout=TIMEOUT_SEC)
        except sqlite3.Error as e:
            raise RecipeDbError(f'DB 를 열 수 없습니다: {self.path} ({e})') from None
        connection.row_factory = sqlite3.Row
        return connection

    def _query(self, sql, args=()):
        connection = self._connect()
        try:
            rows = connection.execute(sql, args).fetchall()
        except sqlite3.OperationalError as e:
            if 'no such table' in str(e):
                raise RecipeDbError(
                    f'뷰 {VIEW} 가 아직 없습니다 - 테이블을 만든 뒤 이 이름의 뷰를 추가하세요') from None
            raise RecipeDbError(f'DB 조회 실패: {e}') from None
        except sqlite3.Error as e:
            raise RecipeDbError(f'DB 조회 실패: {e}') from None
        finally:
            connection.close()
        if rows:
            missing = [c for c in REQUIRED_COLUMNS if c not in rows[0].keys()]
            if missing:
                raise RecipeDbError(f'뷰 {VIEW} 에 필수 컬럼이 없습니다: {", ".join(missing)}')
        return rows

    def list_recipes(self) -> List[str]:
        """DB 에 있는 recipe_id 목록."""
        rows = self._query(f'SELECT * FROM {VIEW}')
        return sorted({str(row['recipe_id']) for row in rows})

    def load_recipe(self, recipe_id: str) -> RecipeDbInfo:
        """Recipe 하나의 포인트 정보를 한 번에 읽는다."""
        rows = self._query(f'SELECT * FROM {VIEW} WHERE recipe_id = ?', (recipe_id,))
        if not rows:
            raise RecipeDbError(f'DB 에 recipe {recipe_id!r} 의 포인트가 없습니다')
        keys = rows[0].keys()
        if 'point_order' in keys:
            rows = sorted(rows, key=lambda r: (r['point_order'] is None, r['point_order']))

        info = RecipeDbInfo(
            recipe_id=recipe_id,
            recipe_version=_text(rows[0], keys, 'recipe_version'),
            product_id=_text(rows[0], keys, 'product_id'))
        for row in rows:
            point_id = str(row['point_id'])
            info.points[point_id] = PointInfo(
                point_id=point_id,
                point_name=_text(row, keys, 'point_name'),
                cable_id=_text(row, keys, 'cable_id'),
                cable_type=_text(row, keys, 'cable_type'),
                max_displacement_mm=_number(row, keys, 'max_displacement_mm', float),
                pull_force_n=_number(row, keys, 'pull_force_n', float),
                repeat_count=_number(row, keys, 'repeat_count', int),
                grip_width_mm=_number(row, keys, 'grip_width_mm', float))
        return info
