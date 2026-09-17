from pydantic import BaseModel, Field, model_validator
from typing import Annotated, Literal
from vitess_ai.schema.base import VitessParameterModel, VtPrgFormat, VtDataFormat, VtTrace

# Constants for array size
NF_MAX = 3  # Assumed based on usage pattern

# Constants
MISSING = -1

class ReadInParameters(VitessParameterModel):
    """Pydantic model for the Vitess Read-in module parameters"""
    
    # Program format
    ePrgFormat: Annotated[VtPrgFormat, Field(
        default=VtPrgFormat.VT_VITESS_FMT,
        description="-f [-] Data format of the program (VT_VITESS_FMT: Vitess, VT_MCSTAS_FMT: McStas, VT_MCPL_FMT: MCPL, VT_MCNPX_FMT and VT_MCNP6_FMT: MCNP). NOTE: VT_KDS_FMT is deprecated - use the separate 'kdsource' module instead.",
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
    Weight: Annotated[list[Annotated[float, Field(ge=0.0, le=1.0)]], Field(
        default=[],
        max_length=NF_MAX,
        description=(
            "-a -b -d [-] Relative weights of the input files, each between 0 "
            "and 1 and proportional to that file's number of started "
            "trajectories. read_in divides each weight by their total, so it "
            "is the ratio that decides the beam"
        ),
        json_schema_extra={"flag": "-a -b -d"}
    )]
    
    # Factor to normalize to source intensity
    FactInt: Annotated[float, Field(
        default=1.0,
        gt=0,
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
        ge=-1,
        description="-C [-] Only for VITESS format: Read only events with a given color",
        json_schema_extra={"flag": "-C"}
    )]
    
    # Number of repetitions
    nRep: Annotated[int, Field(
        default=1,
        ge=1,
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

    @model_validator(mode="after")
    def input_files_have_weights(self) -> "ReadInParameters":
        """Every input file needs the weight in the matching slot.

        There is no rule here about what the weights add up to, and that is
        measured rather than assumed: VITESS 3.8 ``read_in`` divides each weight
        by their total, so ``[1.0, 1.0]`` and ``[0.5, 0.5]`` produce the same
        beam to the last digit, as do ``[2.0, 6.0]`` and ``[0.25, 0.75]``. The
        documentation's "their sum should give 1" is a convention that makes a
        configuration readable, not a condition the binary imposes -- and a
        validator that refuses ``[1.0, 1.0]`` refuses a correct simulation.
        What does matter is the ratio, which nothing here can check.
        """
        if not self.sInputFileName:
            raise ValueError("at least one input file is required")
        if len(self.sInputFileName) != len(self.Weight):
            raise ValueError("read_in requires one weight per input file")
        return self

    @model_validator(mode="after")
    def file_names_are_not_blank(self) -> "ReadInParameters":
        """A field that names a file must name one.

        A blank name is not "no file": `parameters_to_arguments` skips an empty
        string, so `sInputFileName=[""]` produced `-a1.0` -- the weight for
        input file 1 -- with no `-A` beside it, and read_in ran with nothing to
        read. `sInstrInfIn` and `sTraceFileName` say "no file" with `None`,
        which the converter drops flag and all; blank is a third state that
        means nothing to anyone.
        """
        for index, name in enumerate(self.sInputFileName, start=1):
            if not name.strip():
                raise ValueError(f"input file {index} has no name")
        for field_name in ("sInstrInfIn", "sTraceFileName"):
            value = getattr(self, field_name)
            if value is not None and not value.strip():
                raise ValueError(
                    f"{field_name} must be a file name or null, not an empty string"
                )
        return self


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
        Weight=[0.75, 0.25],
        FactInt=2.0,
        iSurface=5,
        nRep=3,
        maxEv=1000000,
        sample=1
    )
    
    print(f"\nCustom config created with ePrgFormat: {custom_config.ePrgFormat}")
