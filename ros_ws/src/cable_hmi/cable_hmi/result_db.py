"""
검사 결과(PointResult)를 SQLite 에 쓰고 읽는다.

테이블 inspection_result: 검사 1회(run_id)의 Point 1개 = 1행. 같은 run 의 같은 Point 를 다시
저장하면 덮어쓴다(재검사, SYNC 재전송). 테이블이 없으면 저장할 때 만든다. 레시피 쪽(recipe_db.py,
뷰 v_recipe_point)과 같은 DB 파일을 써도 되고 다른 파일을 써도 된다.

  - 쓰기(save)는 result_recorder_node 만 한다. HMI 화면 프로세스는 쓰지 않는다.
  - 읽기(latest_by_point)는 '통합 조회' 탭이 백그라운드 스레드에서 한다. 읽기 전용으로 연다.

Qt 에 의존하지 않는다.
"""

from dataclasses import fields
from datetime import datetime
import json
from pathlib import Path
import sqlite3
from typing import Dict, Tuple

from . import interface as itf

TABLE = 'inspection_result'
TIMEOUT_SEC = 1.0        # DB 가 잠겨 있어도 오래 멈추지 않게

_SQL_TYPES = {str: 'TEXT', int: 'INTEGER', float: 'REAL'}
_JSON_TYPE = 'TEXT'      # 그 밖의 필드(좌표 목록 task / joint)는 JSON 글자로 저장한다
# db_saved 는 '저장됐는가' 를 알리는 표시라서 저장하지 않는다(저장된 행은 당연히 저장된 것이다).
_FIELDS = [f for f in fields(itf.PointResult) if f.name != 'db_saved']
_COLUMNS = [f.name for f in _FIELDS] + ['saved_at']

_CREATE = (
    f'CREATE TABLE IF NOT EXISTS {TABLE} ('
    + ', '.join(f'{f.name} {_SQL_TYPES.get(f.type, _JSON_TYPE)}' for f in _FIELDS)
    + ', saved_at TEXT, PRIMARY KEY (run_id, point_id))')
_UPSERT = (
    f'INSERT OR REPLACE INTO {TABLE} ({", ".join(_COLUMNS)}) '
    f'VALUES ({", ".join("?" for _ in _COLUMNS)})')


class ResultDbError(Exception):
    """결과를 쓰거나 읽지 못함. 메시지는 그대로 로그에 쓸 수 있는 이유다."""


class ResultDb:
    """SQLite 파일 하나에 대한 창구. 호출할 때마다 열고 닫는다."""

    def __init__(self, path):
        self.path = Path(path).expanduser()

    def save(self, result: itf.PointResult):
        """결과 1건을 저장한다. 파일·테이블이 없으면 만든다."""
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            connection = sqlite3.connect(str(self.path), timeout=TIMEOUT_SEC)
        except (OSError, sqlite3.Error) as e:
            raise ResultDbError(f'DB 를 열 수 없습니다: {self.path} ({e})') from None
        try:
            with connection:                # commit / rollback
                connection.execute(_CREATE)
                self._add_missing_columns(connection)
                values = [getattr(result, f.name) if f.type in _SQL_TYPES
                          else json.dumps(getattr(result, f.name)) for f in _FIELDS]
                values.append(datetime.now().isoformat(timespec='seconds'))
                connection.execute(_UPSERT, values)
        except sqlite3.Error as e:
            raise ResultDbError(f'결과 저장 실패: {e}') from None
        finally:
            connection.close()

    @staticmethod
    def _add_missing_columns(connection):
        """예전에 만든 테이블에도 쓸 수 있게, 그 뒤 PointResult 에 늘어난 필드를 열로 추가한다."""
        existing = {row[1] for row in connection.execute(f'PRAGMA table_info({TABLE})')}
        for f in _FIELDS:
            if f.name not in existing:
                sql_type = _SQL_TYPES.get(f.type, _JSON_TYPE)
                connection.execute(f'ALTER TABLE {TABLE} ADD COLUMN {f.name} {sql_type}')

    def latest_by_point(self) -> Dict[Tuple[str, str], itf.PointResult]:
        """
        포인트별 가장 최근 결과: {(recipe_id, point_id): PointResult}.

        DB 파일이나 테이블이 아직 없는 것은 '저장된 결과가 없음' 이다(빈 dict).
        """
        if not self.path.is_file():
            return {}
        try:
            connection = sqlite3.connect(
                f'file:{self.path}?mode=ro', uri=True, timeout=TIMEOUT_SEC)
        except sqlite3.Error as e:
            raise ResultDbError(f'DB 를 열 수 없습니다: {self.path} ({e})') from None
        connection.row_factory = sqlite3.Row
        try:
            rows = connection.execute(f'SELECT * FROM {TABLE} ORDER BY stamp, saved_at').fetchall()
        except sqlite3.OperationalError as e:
            if 'no such table' in str(e):
                return {}
            raise ResultDbError(f'결과 조회 실패: {e}') from None
        except sqlite3.Error as e:
            raise ResultDbError(f'결과 조회 실패: {e}') from None
        finally:
            connection.close()

        latest = {}
        for row in rows:                    # 시간 순이므로 뒤에 온 것이 남는다
            keys = row.keys()
            result = itf.PointResult(db_saved=True)
            for f in _FIELDS:
                if f.name not in keys or row[f.name] is None:
                    continue
                if f.type in _SQL_TYPES:
                    setattr(result, f.name, f.type(row[f.name]))
                else:
                    try:
                        setattr(result, f.name, json.loads(row[f.name]))
                    except ValueError:
                        pass                # 손으로 고친 행 등: 그 값만 비워 둔다
            latest[(result.recipe_id, result.point_id)] = result
        return latest
