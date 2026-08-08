import threading

class CaseStore:
    def __init__(self):
        self._lock = threading.Lock()
        self._cases: dict[str, dict] = {}
        self._seq = 0

    def upsert(self, case: dict):
        with self._lock:
            existing = self._cases.get(case["case_id"])
            if existing:
                case = {**existing, **case}
            else:
                self._seq += 1
                case = {**case, "seq": self._seq}
            self._cases[case["case_id"]] = case

    def get(self, case_id):
        with self._lock:
            return self._cases.get(case_id)

    def list(self, pack_id=None):
        with self._lock:
            cases = [c for c in self._cases.values()
                     if pack_id is None or c["pack_id"] == pack_id]
        return sorted(cases, key=lambda c: c["seq"], reverse=True)
