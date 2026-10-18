"""Explicit immutable configuration; no environment or file loading."""

from dataclasses import dataclass
from pathlib import Path

from arqon_os import __version__
from arqon_os.core.errors import ConfigurationError


@dataclass(frozen=True)
class ArqonConfig:
    """Pure configuration values, not a workspace or database initializer.

    Environments are development, testing, staging and production (case-sensitive).
    Relative paths stay relative; construction does not resolve or create them.
    Approval is mandatory in this release. Enabling networking records intent
    only; configuration itself never performs network activity.
    """

    app_name: str = "Arqon OS"
    version: str = __version__
    environment: str = "development"
    database_path: Path = Path(".arqon-os/arqon.db")
    require_approval: bool = True
    network_enabled: bool = False

    def __post_init__(self) -> None:
        if not isinstance(self.environment, str) or self.environment not in (
            "development", "testing", "staging", "production"
        ):
            raise ConfigurationError("Unsupported environment.")
        if self.require_approval is not True:
            raise ConfigurationError("Approval cannot be disabled in this release.")
        if type(self.network_enabled) is not bool:
            raise ConfigurationError("network_enabled must be a boolean.")
        if not isinstance(self.database_path, Path):
            raise ConfigurationError("database_path must be a pathlib.Path.")
        for value in (self.app_name, self.version):
            if not isinstance(value, str) or not value.strip():
                raise ConfigurationError("Application name and version must be nonempty strings.")
