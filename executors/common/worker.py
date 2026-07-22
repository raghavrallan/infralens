"""Cross-platform RQ worker used by the provider executor containers."""
from rq import SimpleWorker
from rq.timeouts import TimerDeathPenalty


class Worker(SimpleWorker):
    death_penalty_class = TimerDeathPenalty

