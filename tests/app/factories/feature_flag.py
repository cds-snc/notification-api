import os
from app.feature_flags import FeatureFlag


def mock_feature_flag(mocker, feature_flag: FeatureFlag, enabled: str) -> None:
    mocker.patch.dict(os.environ, {feature_flag.value: enabled})
