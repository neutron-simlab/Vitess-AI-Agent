from pydantic import BaseModel, Field
from typing import Annotated, Literal
from enum import IntEnum

# Constants for array size
NF_MAX = 3  # Assumed based on usage pattern

# Enums from defines.h
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

# Constants
MISSING = -1

class ReadInParameters(BaseModel):
    """Pydantic model for the Vitess Read-in module parameters"""
    
    # Program format
    ePrgFormat: Annotated[VtPrgFormat, Field(
        default=VtPrgFormat.VT_VITESS_FMT,
        description="Data format of the program (VT_VITESS_FMT: Vitess, VT_MCSTAS_FMT: McStas, VT_MCPL_FMT: MCPL, VT_MCNPX_FMT and VT_MCNP6_FMT: MCNP)"
    )]
    
    # Data format
    eDatFormat: Annotated[VtDataFormat, Field(
        default=VtDataFormat.VT_EXPONENTIAL,
        description="Format of the data to read (VT_EXPONENTIAL, VT_FLOAT, VT_BINARY)"
    )]
    
    # Input file names (char* array in C++)
    sInputFileName: Annotated[list[str], Field(
        max_length=NF_MAX,
        description="Names of the input files (-A -B -D flags)"
    )]
    
    # Weights (double array in C++)
    Weight: Annotated[list[float], Field(
        max_length=NF_MAX,
        description="Weights of the input files (-a -b -d flags)"
    )]
    
    # Factor to normalize to source intensity
    FactInt: Annotated[float, Field(
        default=1.0,
        description="Factor to normalize to the source intensity (-I flag)"
    )]
    
    # Surface ID
    iSurface: Annotated[int, Field(
        default=MISSING,
        description="Surface ID: if given, only neutrons with this ID are considered (-s flag)"
    )]
    
    # Detect color
    iDetectColor: Annotated[int, Field(
        default=-1,
        description="Only for VITESS format: Read only events with a given color (-C flag)"
    )]
    
    # Number of repetitions
    nRep: Annotated[int, Field(
        default=1,
        description="Number of times the input is read (-R flag)"
    )]
    
    # Maximum events
    maxEv: Annotated[float, Field(
        default=-1,
        description="Maximal number of events read (-M flag)"
    )]
    
    # Random sample flag
    sample: Annotated[int, Field(
        default=0,
        description="Random sample or not (-J flag)"
    )]
    
    # KDE usage flag
    use_kde: Annotated[int, Field(
        default=1,
        description="Whether to use KDE or just read the particles from the MCPL file referred in the xml file (-K flag)"
    )]
    
    # External variables (extern in C++)
    sInstrInfIn: Annotated[str | None, Field(
        default=None,
        description="Instrument file that is read (default 'instrument.inf') (--I flag)"
    )]
    
    sTraceFileName: Annotated[str | None, Field(
        default=None,
        description="Name of the file containing the trajectories to be traced or started (-T flag)"
    )]
    
    eTraceMode: Annotated[VtTrace, Field(
        default=VtTrace.NO_TRACING,
        description="Tracing mode: NO_TRACING (no tracing), WRITE_TRC_FILES (write trace files for traj. of interest), ONLY_TRC_TRAJ (simulation only with traj. of interest) (-t flag)"
    )]

    # class Config:
    #     use_enum_values = True
    #     validate_assignment = True

class InitialResponseReadIn(BaseModel): 
    """
    This is the default response model for each module at the initialization of the Read-in module.
    Always use this tool to structure your response to the user.
    """
    response: Annotated[Literal['Default Setup', 'Customize', 'Not Known'], 
                        Field(description="Initial read-in module response type")]