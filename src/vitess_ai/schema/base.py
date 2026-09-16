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

class VtMonPar(IntEnum):
    """
    Enumeration for monitor parameter types used by monitor1D and monitor2D modules.
    """
    NO_PAR = 0
    POS_X = 17
    POS_Y = 1
    POS_Z = 2
    DIV_Y = 3
    DIV_Z = 4
    LAMBDA = 5
    ENERGY = 6
    TIME = 7
    K_Y = 8
    K_Z = 9
    POS_R = 10
    POS_PHI = 11
    POS_THETA = 18
    DIR_PHI = 15
    DIR_THETA = 16
    COL_VERT = 12
    COL_HOR = 13
    COLOR = 14

class VtFiltComb(IntEnum):
    """
    Enumeration for filter combination types.
    """
    NO_FCOMB = -1
    OR_OR_OR = 0
    AND_AND_AND = 1
    AND_OR_AND = 2

class VtFormat2D(IntEnum):
    """
    Enumeration for 2D output format types.
    """
    NO_2D_FORMAT = -1
    MATRIX = 0
    XYZ = 1
    MATR_CMPT = 2
    XYZ_CMPT = 3
    MATR_INT = 4

class FillingStage(BaseModel):
    """
    This is the model to store the information about the parameters filling process, either it is processing, completed, or error.
    Always use this tool to structure your response to the user.
    """
    stage: Literal["processing", "completed", "error"]


def get_field_flag(model_class, field_name: str) -> str:
    """Get the flag value for a field."""
    field_info = model_class.model_fields.get(field_name)
    if not field_info or not hasattr(field_info, 'json_schema_extra') or not field_info.json_schema_extra:
        return ""
    return field_info.json_schema_extra.get("flag", "")