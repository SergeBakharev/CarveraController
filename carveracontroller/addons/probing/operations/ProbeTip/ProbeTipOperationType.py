from enum import Enum

from carveracontroller.addons.probing.operations.ProbeTip.ProbeTipOperation import (
    ProbeTipOperationAnchor,
    ProbeTipOperationBore,
    ProbeTipOperationBoss,
)


class ProbeTipOperationType(Enum):
    Bore = ProbeTipOperationBore("Bore", True, False, False, "")
    BossX = ProbeTipOperationBoss("BossX", True, False, False, "")
    BossY = ProbeTipOperationBoss("BossY", False, True, False, "")
    Anchor2 = ProbeTipOperationAnchor("Anchor2", False, False, False, "")
