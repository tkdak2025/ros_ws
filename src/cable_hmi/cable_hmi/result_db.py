"""
검사 결과(PointResult)를 SQLite 에 쓰고 읽는다.

테이블 inspection_result: 검사 1회(run_id)의 Point 1개 = 1행. 같은 run 의 같은 Point 를 다시
저장하면 덮어쓴다(재검사, SYNC 재전송). 테이블이 없으면 저장할 때 만든다. 레시피 쪽(recipe_db.py,
뷰 v_recipe_point)과 같은 DB 파일을 써도 되고 다른 파일을 써도 된다.

테이블 inspection_run: 검사 1회(run_id) = 1행. 언제 시작해 언제, 왜 끝났는지(end_reason:
COMPLETED / STOP / ERROR / COMM_ERROR / INIT_FAIL / ABORTED / LOST)와 제품 판정, Point 집계를 남긴다.
ended_at 이 비어 있는 행은 끝나는 것을 보지 못한 검사다(저장 노드가 먼저 꺼짐 등).

  - 쓰기(save)는 result_recorder_node 만 한다. HMI 화면 프로세스는 공용 DB 에 쓰지 않는다.
  - 읽기(latest_by_point)는 '통합 조회' 탭이 백그라운드 스레드에서 한다. 읽기 전용으로 연다.
  - 예외: export_run() 은 HMI 의 '결과 파일 저장' 버튼이 부른다. 공용 DB 가 아니라 새 파일을
    만들기만 하므로 다른 프로세스와 부딪히지 않는다.

Qt 에 의존하지 않는다.
"""

import csv
from dataclasses import fields
from datetime import datetime
import json
from pathlib import Path
import sqlite3
from typing import Dict, List, Tuple

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


RUN_TABLE = 'inspection_run'
_CREATE_RUN = (
    f'CREATE TABLE IF NOT EXISTS {RUN_TABLE} ('
    'run_id INTEGER PRIMARY KEY, recipe_id TEXT, recipe_version TEXT, product_id TEXT, '
    'started_at TEXT, ended_at TEXT, end_reason TEXT, product_result TEXT, total_points INTEGER, '
    'pass_count INTEGER, fail_count INTEGER, missing_count INTEGER)')


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

    def _write(self, statements):
        """여러 문장 [(sql, 값)] 을 한 트랜잭션으로 실행한다."""
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            connection = sqlite3.connect(str(self.path), timeout=TIMEOUT_SEC)
        except (OSError, sqlite3.Error) as e:
            raise ResultDbError(f'DB 를 열 수 없습니다: {self.path} ({e})') from None
        try:
            with connection:
                for sql, values in statements:
                    connection.execute(sql, values)
        except sqlite3.Error as e:
            raise ResultDbError(f'작업 기록 저장 실패: {e}') from None
        finally:
            connection.close()

    def save_run_start(self, status: itf.SystemStatus):
        """검사 1회가 시작됐다. 같은 run_id 가 있으면 새로 쓴다(mock 은 켤 때마다 1 부터 센다)."""
        now = datetime.now().isoformat(timespec='seconds')
        self._write([
            (_CREATE_RUN, ()),
            (f'INSERT OR REPLACE INTO {RUN_TABLE} (run_id, recipe_id, recipe_version, product_id, '
             'started_at, total_points) VALUES (?, ?, ?, ?, ?, ?)',
             (status.run_id, status.recipe_id, status.recipe_version, status.product_id, now,
              status.total_points))])

    def save_run_end(self, status: itf.SystemStatus, end_reason: str):
        """검사 1회가 끝났다. Point 집계는 저장된 결과(inspection_result)에서 센다."""
        now = datetime.now().isoformat(timespec='seconds')
        counts = {'PASS': 0, 'FAIL': 0, 'MISSING': 0}
        for result in self.results_of_run(status.run_id):
            counts[itf.ResultCode.category(result)] += 1
        self._write([
            (_CREATE_RUN, ()),
            (f'INSERT OR IGNORE INTO {RUN_TABLE} '
             '(run_id, recipe_id, recipe_version, product_id) VALUES (?, ?, ?, ?)',
             (status.run_id, status.recipe_id, status.recipe_version, status.product_id)),
            (f'UPDATE {RUN_TABLE} SET ended_at = ?, end_reason = ?, product_result = ?, '
             'total_points = ?, pass_count = ?, fail_count = ?, missing_count = ? '
             'WHERE run_id = ?',
             (now, end_reason, status.product_result, status.total_points,
              counts['PASS'], counts['FAIL'], counts['MISSING'], status.run_id))])

    def results_of_run(self, run_id: int):
        """그 run 에 저장된 결과 코드 목록. 테이블이 아직 없으면 빈 목록."""
        if not self.path.is_file():
            return []
        try:
            connection = sqlite3.connect(
                f'file:{self.path}?mode=ro', uri=True, timeout=TIMEOUT_SEC)
            try:
                rows = connection.execute(
                    f'SELECT result FROM {TABLE} WHERE run_id = ?', (run_id,)).fetchall()
            finally:
                connection.close()
        except sqlite3.Error:
            return []
        return [str(row[0]) for row in rows]

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


def export_run(directory, results: List[itf.PointResult],
               status: itf.SystemStatus) -> Tuple[Path, Path]:
    """
    지금 화면에 있는 검사 1회의 결과만 새 파일 둘(.db, .csv)에 담는다. (db 경로, csv 경로).

    공용 DB 는 열지도 않는다 - 늘 새 파일을 만들므로 저장 노드와 부딪히지 않는다. .db 는 공용 DB 와
    같은 스키마(inspection_result + 요약 1행 inspection_run)라서 같은 쿼리로 읽을 수 있고,
    .csv 는 엑셀에서 바로 열린다(한글이 깨지지 않게 BOM 을 붙인다).

    inspection_run 의 시작·종료 시각은 결과에 실려 온 stamp 의 처음과 끝이다(내보낸 시각이 아니다).
    """
    if not results:
        raise ResultDbError('저장할 검사 결과가 없습니다.')
    directory = Path(directory).expanduser()
    run_id = status.run_id or results[0].run_id
    name = f'run_{run_id}_{datetime.now().strftime("%Y%m%d_%H%M%S")}'
    db_path, csv_path = directory / f'{name}.db', directory / f'{name}.csv'

    db = ResultDb(db_path)
    for result in results:
        db.save(result)

    stamps = sorted(r.stamp for r in results if r.stamp)
    counts = {'PASS': 0, 'FAIL': 0, 'MISSING': 0}
    for result in results:
        counts[itf.ResultCode.category(result.result)] += 1
    db._write([
        (_CREATE_RUN, ()),
        (f'INSERT OR REPLACE INTO {RUN_TABLE} (run_id, recipe_id, recipe_version, product_id, '
         'started_at, ended_at, end_reason, product_result, total_points, '
         'pass_count, fail_count, missing_count) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)',
         (run_id, status.recipe_id, status.recipe_version, status.product_id,
          stamps[0] if stamps else '', stamps[-1] if stamps else '',
          status.end_reason, status.product_result,
          status.total_points or len(results),
          counts['PASS'], counts['FAIL'], counts['MISSING']))])

    try:
        with csv_path.open('w', encoding='utf-8-sig', newline='') as handle:
            writer = csv.writer(handle)
            writer.writerow([f.name for f in _FIELDS])
            for result in results:
                writer.writerow([
                    getattr(result, f.name) if f.type in _SQL_TYPES
                    else json.dumps(getattr(result, f.name)) for f in _FIELDS])
    except OSError as e:
        raise ResultDbError(f'CSV 를 쓸 수 없습니다: {csv_path} ({e})') from None
    return db_path, csv_path
