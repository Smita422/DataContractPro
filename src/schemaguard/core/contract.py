"""Data Contract specification models, Pydantic validation, and YAML loader."""

from pathlib import Path
import re
from typing import Any, Dict, List, Literal, Optional
from pydantic import BaseModel, Field, field_validator, model_validator
import yaml

from schemaguard.utils.logger import logger

VALID_DATA_TYPES = {"string", "integer", "float", "boolean", "timestamp", "date"}
VALID_COMPATIBILITY_MODES = {"BACKWARD", "FULL", "NONE"}
DEFAULT_CONTRACTS_DIR = Path("contracts")


class ContractError(Exception):
    """Base exception for data contract operations."""
    pass


class ContractNotFoundError(ContractError):
    """Raised when a requested contract file cannot be found."""
    pass


class InvalidContractError(ContractError):
    """Raised when a contract file is structurally or semantically invalid."""
    pass


class ConstraintRules(BaseModel):
    """Validation rules and boundaries applicable to a column."""

    min: Optional[float] = None
    max: Optional[float] = None
    min_length: Optional[int] = Field(default=None, ge=0)
    max_length: Optional[int] = Field(default=None, ge=0)
    pattern: Optional[str] = None
    allowed_values: Optional[List[str]] = None

    @field_validator("pattern")
    @classmethod
    def validate_regex_pattern(cls, val: Optional[str]) -> Optional[str]:
        if val is not None:
            try:
                re.compile(val)
            except re.error as e:
                raise ValueError(f"Invalid regex pattern '{val}': {e}")
        return val

    @model_validator(mode="after")
    def validate_bounds(self) -> "ConstraintRules":
        if self.min is not None and self.max is not None and self.min > self.max:
            raise ValueError(f"min ({self.min}) cannot be greater than max ({self.max})")
        if (
            self.min_length is not None
            and self.max_length is not None
            and self.min_length > self.max_length
        ):
            raise ValueError(
                f"min_length ({self.min_length}) cannot be greater than max_length ({self.max_length})"
            )
        return self


class ColumnDefinition(BaseModel):
    """Definition and constraints for a single dataset column."""

    name: str = Field(..., min_length=1)
    type: str = Field(..., min_length=1)
    nullable: bool = False
    primary_key: bool = False
    unique: bool = False
    default: Optional[Any] = None
    description: Optional[str] = None
    constraints: Optional[ConstraintRules] = None

    @field_validator("type")
    @classmethod
    def validate_type(cls, val: str) -> str:
        normalized = val.lower().strip()
        if normalized not in VALID_DATA_TYPES:
            raise ValueError(
                f"Unsupported type '{val}'. Allowed types: {sorted(VALID_DATA_TYPES)}"
            )
        return normalized


class DerivedFieldDefinition(BaseModel):
    """Specification of a field computed from other columns."""

    name: str = Field(..., min_length=1)
    type: str = Field(..., min_length=1)
    expression: str = Field(..., min_length=1)
    description: Optional[str] = None

    @field_validator("type")
    @classmethod
    def validate_type(cls, val: str) -> str:
        normalized = val.lower().strip()
        if normalized not in VALID_DATA_TYPES:
            raise ValueError(
                f"Unsupported type '{val}'. Allowed types: {sorted(VALID_DATA_TYPES)}"
            )
        return normalized


class SLADefinition(BaseModel):
    """Quality SLA parameters for the dataset."""

    max_quarantine_percent: float = Field(default=5.0, ge=0.0, le=100.0)


class Contract(BaseModel):
    """Top-level Data Contract specification."""

    dataset: str = Field(..., min_length=1)
    version: str = Field(..., pattern=r"^\d+\.\d+\.\d+$")
    owner: str = Field(..., min_length=1)
    domain: Optional[str] = None
    compatibility_mode: Literal["BACKWARD", "FULL", "NONE"] = "BACKWARD"
    description: Optional[str] = None
    columns: List[ColumnDefinition] = Field(..., min_length=1)
    derived_fields: List[DerivedFieldDefinition] = Field(default_factory=list)
    sla: Optional[SLADefinition] = None

    @model_validator(mode="after")
    def validate_unique_column_names(self) -> "Contract":
        col_names = [c.name for c in self.columns]
        if len(col_names) != len(set(col_names)):
            duplicates = [name for name in col_names if col_names.count(name) > 1]
            raise ValueError(f"Duplicate column names in contract: {set(duplicates)}")
        return self

    def get_column(self, name: str) -> Optional[ColumnDefinition]:
        """Look up a column definition by its name."""
        for col in self.columns:
            if col.name == name:
                return col
        return None

    def get_primary_key(self) -> Optional[str]:
        """Return the primary key column name if defined."""
        for col in self.columns:
            if col.primary_key:
                return col.name
        return None

    @property
    def column_names(self) -> List[str]:
        """Return list of column names defined in contract."""
        return [c.name for c in self.columns]


def _parse_semver(version_str: str) -> tuple[int, int, int]:
    """Parse a semantic version string (e.g. '1.1.0' or 'v1.1.0') into an int tuple."""
    cleaned = version_str.lstrip("v").strip()
    parts = cleaned.split(".")
    if len(parts) != 3:
        raise ValueError(f"Invalid semver: '{version_str}'")
    return int(parts[0]), int(parts[1]), int(parts[2])


def load_contract_from_yaml(yaml_path: Path | str) -> Contract:
    """Load, parse, and validate a contract from a YAML file path."""
    path = Path(yaml_path)
    if not path.is_file():
        raise ContractNotFoundError(f"Contract file not found at: {path}")

    try:
        with open(path, "r", encoding="utf-8") as f:
            raw_data = yaml.safe_load(f)
    except yaml.YAMLError as exc:
        raise InvalidContractError(f"YAML parsing error in {path}: {exc}") from exc

    if not isinstance(raw_data, dict):
        raise InvalidContractError(f"Expected YAML dictionary in {path}, got {type(raw_data)}")

    try:
        contract = Contract(**raw_data)
        logger.debug(f"Loaded contract {contract.dataset} v{contract.version} from {path}")
        return contract
    except Exception as exc:
        raise InvalidContractError(f"Contract validation error in {path}: {exc}") from exc


def load_contract(
    dataset_name: str,
    version: Optional[str] = None,
    contracts_dir: Optional[Path | str] = None,
) -> Contract:
    """Discover and load a contract for a given dataset and version.

    If version is None or 'latest', automatically resolves the latest semantic version.
    """
    base_dir = Path(contracts_dir) if contracts_dir else DEFAULT_CONTRACTS_DIR
    dataset_dir = base_dir / dataset_name

    if not dataset_dir.is_dir():
        raise ContractNotFoundError(
            f"No contracts directory found for dataset '{dataset_name}' at {dataset_dir}"
        )

    yaml_files = list(dataset_dir.glob("*.yaml")) + list(dataset_dir.glob("*.yml"))
    if not yaml_files:
        raise ContractNotFoundError(
            f"No contract YAML files found for dataset '{dataset_name}' in {dataset_dir}"
        )

    if version is not None and version.lower() != "latest":
        target_version = version.lstrip("v")
        for file_path in yaml_files:
            file_version = file_path.stem.lstrip("v")
            if file_version == target_version:
                return load_contract_from_yaml(file_path)
        raise ContractNotFoundError(
            f"Contract version '{version}' not found for dataset '{dataset_name}'. "
            f"Available versions: {[f.stem for f in yaml_files]}"
        )

    # Resolve latest semver
    def get_file_semver(p: Path) -> tuple[int, int, int]:
        try:
            return _parse_semver(p.stem)
        except Exception:
            return (-1, -1, -1)

    sorted_files = sorted(yaml_files, key=get_file_semver)
    latest_file = sorted_files[-1]
    return load_contract_from_yaml(latest_file)


def list_dataset_contracts(
    dataset_name: str, contracts_dir: Optional[Path | str] = None
) -> List[str]:
    """List all available contract versions for a specific dataset."""
    base_dir = Path(contracts_dir) if contracts_dir else DEFAULT_CONTRACTS_DIR
    dataset_dir = base_dir / dataset_name
    if not dataset_dir.is_dir():
        return []

    yaml_files = list(dataset_dir.glob("*.yaml")) + list(dataset_dir.glob("*.yml"))
    versions = []
    for f in yaml_files:
        try:
            _parse_semver(f.stem)
            versions.append(f.stem.lstrip("v"))
        except ValueError:
            continue
    return sorted(versions, key=_parse_semver)


def list_all_contracts(contracts_dir: Optional[Path | str] = None) -> Dict[str, List[str]]:
    """List all registered datasets and their corresponding contract versions."""
    base_dir = Path(contracts_dir) if contracts_dir else DEFAULT_CONTRACTS_DIR
    if not base_dir.is_dir():
        return {}

    result = {}
    for entry in base_dir.iterdir():
        if entry.is_dir() and not entry.name.startswith("."):
            versions = list_dataset_contracts(entry.name, contracts_dir=base_dir)
            if versions:
                result[entry.name] = versions
    return result
