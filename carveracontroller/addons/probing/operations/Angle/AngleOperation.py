import copy

from carveracontroller.addons.probing.operations.Angle.AngleParameterDefinitions import AngleParameterDefinitions
from carveracontroller.addons.probing.operations.OperationsBase import OperationsBase, ProbeSettingDefinition
from carveracontroller.addons.probing.operations.SingleAxis.SingleAxisProbeParameterDefinitions import (
    SingleAxisProbeParameterDefinitions,
)


class AngleOperation(OperationsBase):
    imagePath: str

    def __init__(self, title, requires_x, requires_y, invert_direction, image_path, **kwargs):
        self.title = title
        self.imagePath = image_path
        self.requires_x = requires_x
        self.requires_y = requires_y
        self.invert_direction = invert_direction

    def generate(self, input_config: dict[str, float]):
        config = copy.deepcopy(input_config)

        if self.requires_x:
            config[AngleParameterDefinitions.YAxisDistance.code] = ""
        if self.requires_y:
            config[AngleParameterDefinitions.XAxisDistance.code] = ""

        # Make sure the probe depth is set to the default value if it is not set.
        depth = AngleParameterDefinitions.ProbeDepth
        if not str(config.get(depth.code, "")).strip():
            config[depth.code] = depth.default

        super().apply_direction(depth.code, config, self.invert_direction)

        return "M465" + self.config_to_gcode(config)

    def get_missing_config(self, config: dict[str, float]):
        if self.requires_x:
            definition = AngleParameterDefinitions.XAxisDistance
            if definition.code not in config or not config[definition.code].strip():
                return definition
        if self.requires_y:
            definition = AngleParameterDefinitions.YAxisDistance
            if definition.code not in config or not config[definition.code].strip():
                return definition

        required_definitions = {
            name: value
            for name, value in AngleParameterDefinitions.__dict__.items()
            if isinstance(value, ProbeSettingDefinition) and value.is_required
        }

        return super().validate_required(required_definitions, config)
