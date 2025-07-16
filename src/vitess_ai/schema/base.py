from pydantic import BaseModel
from typing import Literal
from enum import IntEnum

class VtPrgFormat(IntEnum):
    VT_VITESS_FMT = 1
    VT_MCSTAS_FMT = 2
    VT_MCPL_FMT = 3
    VT_MCNPX_FMT = 4
    VT_MCNP6_FMT = 5
    VT_SSW_FMT = 6
    VT_KDS_FMT = 7

class VtDataFormat(IntEnum):
    VT_EXPONENTIAL = 0
    VT_FLOAT = 1
    VT_BINARY = 2

class VtTrace(IntEnum):
    NO_TRACING = 0
    WRITE_TRC_FILES = 1
    ONLY_TRC_TRAJ = 2

class VtSeparator(IntEnum):
    VT_BLANK = 0
    VT_TABULATOR = 1


class FillingStage(BaseModel):
    """
    This is the model to store the information about the parameters filling process, either it is processing or complete.
    Always use this tool to structure your response to the user.
    """
    stage: Literal["processing", "complete"]
