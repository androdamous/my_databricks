from dataclasses import dataclass, field
from enum import Enum
from typing import Optional, Union


class RunMode(str, Enum):
    INCREMENTAL = "incremental"
    RERUN = "rerun"
    MANUAL = "manual"


@dataclass
class SingleScope:
    data_date: str


@dataclass
class BulkScope:
    data_dates: Optional[list[str]] = None
    from_date: Optional[str] = None
    to_date: Optional[str] = None

    def __post_init__(self):
        if not self.data_dates:
            if self.from_date is None or self.to_date is None:
                raise ValueError("Either data_dates or both from_date and to_date must be provided.")
            self.data_dates = None


@dataclass
class IncrementalRunConfig:
    run_mode: RunMode = field(default=RunMode.INCREMENTAL, init=False)


@dataclass
class ReRunConfig:
    run_mode: RunMode = field(default=RunMode.RERUN, init=False)


@dataclass
class ManualRunConfig:
    skip_dependencies: bool = False
    skip_condition_check: bool = False
    run_mode: RunMode = field(default=RunMode.MANUAL, init=False)


JobScope = Union[SingleScope, BulkScope]
RunConfig = Union[IncrementalRunConfig, ReRunConfig, ManualRunConfig]


@dataclass
class Job:
    job_id: str
    scope: JobScope
    run: RunConfig
