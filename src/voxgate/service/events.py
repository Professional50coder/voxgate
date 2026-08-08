import threading

class EventBus:
    def __init__(self):
        self._cond = threading.Condition()
        self._events: dict[str, list[dict]] = {}

    def publish(self, case_id, event):
        with self._cond:
            self._events.setdefault(case_id, []).append(event)
            self._cond.notify_all()

    def history(self, case_id):
        with self._cond:
            return list(self._events.get(case_id, []))

    def wait(self, case_id, after_index, timeout):
        with self._cond:
            self._cond.wait_for(
                lambda: len(self._events.get(case_id, [])) > after_index, timeout=timeout)
            return list(self._events.get(case_id, [])[after_index:])
