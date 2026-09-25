"""시퀀스 영역에서 공유하는 작업 중지 신호."""



class JobStopped(RuntimeError):
    """STOP/통신 만료에 의한 흐름 종료. 제품 FAIL과 구분한다."""
