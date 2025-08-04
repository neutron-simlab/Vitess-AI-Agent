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

class VtGdeShape(IntEnum):
    """
    Enumeration for guide shape types with detailed descriptions:
    
    VT_CONSTANT (0): Same cross-section on the whole length (usually 1 piece).
    Creates a straight guide with uniform dimensions from entrance to exit.
    
    VT_LINEAR (1): Linearly converging or diverging between entrance and exit (usually 1 piece).
    The cross-section changes smoothly from entrance to exit dimensions.
    
    VT_CURVED (2): Several pieces form part of a regular polygon (only in horizontal plane).
    The first piece is aligned to the preceding, the last to the succeeding module.
    The radius of the circle through the polygon corners and the number of pieces need to be given.
    
    VT_PARABOLIC (3): The guide consists of several straight pieces that approach a parabola,
    which is defined by entrance and exit width. The number of pieces need to be given.
    
    VT_ELLIPTIC (4): The guide consists of several straight pieces that approach an ellipse,
    which is defined by entrance and exit width, and an angle describing the position of the ellipse.
    This angle and the number of pieces need to be given.
    
    VT_FROM_FILE (5): The guide consists of several straight pieces that might have different
    length and different coating and can be converging or diverging. Each piece is described
    by one line in the file; the parameters that have to be given are: Position, width and
    height of the beginning of the piece, reflectivity files for left, right, top and bottom plane.
    
    VT_LIN_CURV (6): The same as curved except that entrance and exit width are different
    (only in horizontal plane). Combines curvature with linear tapering.
    """
    VT_CONSTANT = 0
    VT_LINEAR = 1
    VT_CURVED = 2
    VT_PARABOLIC = 3
    VT_ELLIPTIC = 4
    VT_FROM_FILE = 5
    VT_LIN_CURV = 6

class FillingStage(BaseModel):
    """
    This is the model to store the information about the parameters filling process, either it is processing or complete.
    Always use this tool to structure your response to the user.
    """
    stage: Literal["processing", "completed"]


def get_field_flag(model_class, field_name: str) -> str:
    """Get the flag value for a field."""
    field_info = model_class.model_fields.get(field_name)
    if not field_info or not hasattr(field_info, 'json_schema_extra') or not field_info.json_schema_extra:
        return ""
    return field_info.json_schema_extra.get("flag", "")