"""In-process publishing metrics counters (actual executions only)."""

from __future__ import annotations

from dataclasses import dataclass, field
from threading import Lock


@dataclass
class PublishingMetrics:
    due_posts_discovered: int = 0
    jobs_queued: int = 0
    queue_failures: int = 0
    claims_succeeded: int = 0
    claims_skipped: int = 0
    simulated_publications: int = 0
    retries_scheduled: int = 0
    permanent_failures: int = 0
    uncertain_outcomes: int = 0
    recoveries_requeued: int = 0
    recoveries_requires_review: int = 0
    publish_latency_ms_total: float = 0.0
    publish_latency_samples: int = 0
    scheduling_delay_ms_total: float = 0.0
    scheduling_delay_samples: int = 0
    _lock: Lock = field(default_factory=Lock, repr=False)

    def incr(self, name: str, amount: int = 1) -> None:
        with self._lock:
            current = getattr(self, name)
            setattr(self, name, current + amount)

    def observe_publish_latency_ms(self, value: float) -> None:
        with self._lock:
            self.publish_latency_ms_total += value
            self.publish_latency_samples += 1

    def observe_scheduling_delay_ms(self, value: float) -> None:
        with self._lock:
            self.scheduling_delay_ms_total += value
            self.scheduling_delay_samples += 1

    def snapshot(self) -> dict[str, float | int]:
        with self._lock:
            avg_latency = (
                self.publish_latency_ms_total / self.publish_latency_samples
                if self.publish_latency_samples
                else 0.0
            )
            avg_delay = (
                self.scheduling_delay_ms_total / self.scheduling_delay_samples
                if self.scheduling_delay_samples
                else 0.0
            )
            return {
                "due_posts_discovered": self.due_posts_discovered,
                "jobs_queued": self.jobs_queued,
                "queue_failures": self.queue_failures,
                "claims_succeeded": self.claims_succeeded,
                "claims_skipped": self.claims_skipped,
                "simulated_publications": self.simulated_publications,
                "retries_scheduled": self.retries_scheduled,
                "permanent_failures": self.permanent_failures,
                "uncertain_outcomes": self.uncertain_outcomes,
                "recoveries_requeued": self.recoveries_requeued,
                "recoveries_requires_review": self.recoveries_requires_review,
                "publish_latency_ms_avg": avg_latency,
                "scheduling_delay_ms_avg": avg_delay,
            }


# Process-wide metrics for workers and tests.
METRICS = PublishingMetrics()
