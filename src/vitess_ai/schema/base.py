from pydantic import BaseModel, ConfigDict
from typing import Literal
from enum import IntEnum


class VitessParameterModel(BaseModel):
    """Strict base for every object that becomes a VITESS command line.

    Pydantic ignores unknown fields by default.  That is unsafe here: a model
    typo would be discarded and the schema default would then be recorded as
    though the requested value had passed validation.
    """

    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)

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
    """How the two monitor filter parameters are combined.

    ``NO_FCOMB`` is this schema's "not chosen" sentinel, and it is **not inert**.
    Measured against VITESS 3.8 ``monitor1D`` on a 1000-trajectory beam, a run
    carrying two complete filters keeps every neutron passing *either* of them
    for ``-C-1``, ``-C0`` and ``-C2`` alike; only ``-C1`` keeps those passing
    both. So a configuration that leaves this at ``NO_FCOMB`` with both filters
    set has silently chosen OR, which is the one case the monitor validator
    refuses. With one filter or none, the flag changes nothing at all.
    """
    NO_FCOMB = -1
    OR_OR_OR = 0
    AND_AND_AND = 1
    AND_OR_AND = 2


def validate_monitor_filter_configuration(
    *,
    lambda_minimum: float | None,
    lambda_maximum: float | None,
    parameter_1: VtMonPar,
    minimum_1: float | None,
    maximum_1: float | None,
    parameter_2: VtMonPar,
    minimum_2: float | None,
    maximum_2: float | None,
    combination: VtFiltComb,
) -> None:
    """Refuse a monitor filter VITESS would quietly read as a different filter.

    Each filter is three independent CLI flags -- the parameter and its two
    bounds -- and a bound VITESS is not given is 0 rather than "no bound". It
    never refuses the run. Every rule below was measured against VITESS 3.8
    ``monitor1D`` on a 1000-trajectory beam whose unfiltered total is 6.01e10,
    and each one is here because the half-configured form exits 0 with a plot
    nobody asked for:

    ==========================  ==========================================
    ``-l4`` with no ``-L``      total 0 -- lambda in [4, 0] keeps nothing
    ``-L12`` with no ``-l``     total unchanged -- no filtering at all
    ``-u-0.5`` with no ``-U``   total 3.87e10 -- a filter on [-0.5, 0]
    ``-I1`` with no bounds      total unchanged -- no filtering at all
    ``-u``/``-U`` with no -I    total unchanged -- no filtering at all
    ==========================  ==========================================

    Two things are deliberately **not** refused, because the binary handles them
    correctly and refusing them would make a working configuration
    inexpressible: filter 2 used on its own (measured identical to the same
    filter in slot 1), and a combination set while fewer than two filters are
    active, which changes nothing.
    """

    for label, lower, upper in (
        ("lambda", lambda_minimum, lambda_maximum),
        ("filter 1", minimum_1, maximum_1),
        ("filter 2", minimum_2, maximum_2),
    ):
        if (lower is None) != (upper is None):
            raise ValueError(
                f"{label} needs both a minimum and a maximum, or neither; "
                "VITESS reads a missing bound as 0 rather than as no bound"
            )

    both_filters_in_use = True
    for index, parameter, minimum, maximum in (
        (1, parameter_1, minimum_1, maximum_1),
        (2, parameter_2, minimum_2, maximum_2),
    ):
        has_parameter = parameter != VtMonPar.NO_PAR
        has_limits = minimum is not None and maximum is not None
        if has_parameter and not has_limits:
            raise ValueError(
                f"filter {index} names a parameter but no limits to filter by"
            )
        if has_limits and not has_parameter:
            raise ValueError(f"filter {index} limits require a filter parameter")
        both_filters_in_use = both_filters_in_use and has_parameter

    if both_filters_in_use and combination == VtFiltComb.NO_FCOMB:
        raise ValueError(
            "two filters must say how they combine: filterComb left at NO_FCOMB "
            "keeps every neutron passing either filter, and only AND_AND_AND "
            "keeps those passing both"
        )


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
