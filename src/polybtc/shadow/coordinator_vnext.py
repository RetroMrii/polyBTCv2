"""One operational owner for scheduling, claims and evaluation.

Legacy driver/adapter APIs remain available for research callers. The runtime
uses one object and the same tested methods, without a second claim owner.
"""

from polybtc.shadow.stream_driver_vnext import VNextSnapshotStreamDriver
from polybtc.shadow.adapter_vnext import VNextEvaluationAdapter


class VNextEvaluationCoordinator(VNextSnapshotStreamDriver):
    evaluate = VNextEvaluationAdapter.evaluate

    def __init__(self, *, journal, runner, **kwargs):
        VNextEvaluationAdapter.__init__(self, journal=journal, runner=runner)
        super().__init__(journal=journal, adapter=self, **kwargs)
