from pydantic import BaseModel, Field
from typing import Annotated, Literal
from vitess_ai.schema.base import VtPrgFormat, VtDataFormat, VtTrace

# Constants for array size
NF_MAX = 3  # Assumed based on usage pattern

# Constants
MISSING = -1

class ReadInParameters(BaseModel):
    """Pydantic model for the Vitess Read-in module parameters"""
    
    # Program format
    ePrgFormat: Annotated[VtPrgFormat, Field(
        default=VtPrgFormat.VT_VITESS_FMT,
        description="-f [-] Data format of the program (VT_VITESS_FMT: Vitess, VT_MCSTAS_FMT: McStas, VT_MCPL_FMT: MCPL, VT_MCNPX_FMT and VT_MCNP6_FMT: MCNP)",
        json_schema_extra={"flag": "-f"}
    )]
    
    # Data format
    eDatFormat: Annotated[VtDataFormat, Field(
        default=VtDataFormat.VT_EXPONENTIAL,
        description="-F [-] Format of the data to read (VT_EXPONENTIAL, VT_FLOAT, VT_BINARY)",
        json_schema_extra={"flag": "-F"}
    )]
    
    # Input file names (char* array in C++)
    sInputFileName: Annotated[list[str], Field(
        default=[],
        max_length=NF_MAX,
        description="-A -B -D [-] Names of the input files",
        json_schema_extra={"flag": "-A -B -D"}
    )]
    
    # Weights (double array in C++)
    Weight: Annotated[list[float], Field(
        default=[],
        max_length=NF_MAX,
        description="-a -b -d [-] Weights of the input files",
        json_schema_extra={"flag": "-a -b -d"}
    )]
    
    # Factor to normalize to source intensity
    FactInt: Annotated[float, Field(
        default=1.0,
        description="-I [-] Factor to normalize to the source intensity",
        json_schema_extra={"flag": "-I"}
    )]
    
    # Surface ID
    iSurface: Annotated[int, Field(
        default=MISSING,
        description="-s [-] Surface ID: if given, only neutrons with this ID are considered",
        json_schema_extra={"flag": "-s"}
    )]
    
    # Detect color
    iDetectColor: Annotated[int, Field(
        default=-1,
        description="-C [-] Only for VITESS format: Read only events with a given color",
        json_schema_extra={"flag": "-C"}
    )]
    
    # Number of repetitions
    nRep: Annotated[int, Field(
        default=1,
        description="-R [-] Number of times the input is read",
        json_schema_extra={"flag": "-R"}
    )]
    
    # Maximum events
    maxEv: Annotated[float, Field(
        default=-1,
        description="-M [-] Maximal number of events read",
        json_schema_extra={"flag": "-M"}
    )]
    
    # Random sample flag
    sample: Annotated[int, Field(
        default=0,
        description="-J [-] Random sample or not",
        json_schema_extra={"flag": "-J"}
    )]
    
    # KDE usage flag
    use_kde: Annotated[int, Field(
        default=1,
        description="-K [-] Whether to use KDE or just read the particles from the MCPL file referred in the xml file",
        json_schema_extra={"flag": "-K"}
    )]
    
    # External variables (extern in C++)
    sInstrInfIn: Annotated[str | None, Field(
        default='instrument.inf',
        description="--I [-] Instrument file that is read (default 'instrument.inf')",
        json_schema_extra={"flag": "--I"}
    )]
    
    sTraceFileName: Annotated[str | None, Field(
        default=None,
        description="-T [-] Name of the file containing the trajectories to be traced or started",
        json_schema_extra={"flag": "-T"}
    )]
    
    eTraceMode: Annotated[VtTrace, Field(
        default=VtTrace.NO_TRACING,
        description="-t [-] Tracing mode: NO_TRACING (no tracing), WRITE_TRC_FILES (write trace files for traj. of interest), ONLY_TRC_TRAJ (simulation only with traj. of interest)",
        json_schema_extra={"flag": "-t"}
    )]


class InitialResponseReadIn(BaseModel): 
    """
    This is the default response model for each module at the initialization of the Read-in module.
    Always use this tool to structure your response to the user.
    """
    response: Annotated[Literal['Default Setup', 'Customize', 'Not Known'], 
                        Field(description="Initial read-in module response type")]


# Example usage
if __name__ == "__main__":
    # Create a configuration with default values
    config = ReadInParameters()
    
    # Create custom configuration
    custom_config = ReadInParameters(
        ePrgFormat=VtPrgFormat.VT_MCSTAS_FMT,
        eDatFormat=VtDataFormat.VT_FLOAT,
        sInputFileName=["file1.dat", "file2.dat"],
        Weight=[1.0, 0.5],
        FactInt=2.0,
        iSurface=5,
        nRep=3,
        maxEv=1000000,
        sample=1,
        use_kde=0
    )
    
    print(f"\nCustom config created with ePrgFormat: {custom_config.ePrgFormat}")