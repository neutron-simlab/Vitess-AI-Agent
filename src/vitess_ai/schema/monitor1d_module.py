from typing import Annotated, Literal, Optional
from pydantic import BaseModel, Field
from vitess_ai.schema.base import VtMonPar, VtFiltComb


class Monitor1DParameters(BaseModel):
    """Configuration model for 1D monitor parameters."""
    
    # Monitor file configuration
    fMonitorFilename: Annotated[str, Field(
        default="monitor1D.dat",
        description=("-O [-] Monitor output file containing intensity, its variation, "
                    "and the number of trajectories as a function of the chosen parameter."),
        json_schema_extra={"flag": "-O"}
    )]
    
    # Parameter configuration
    eParX: Annotated[VtMonPar, Field(
        default=VtMonPar.POS_Y,
        description=("-X [-] Parameter on x-axis. The intensity or polarisation is shown "
                    "as a function of this parameter. See parameter list for available options."),
        json_schema_extra={"flag": "-X"}
    )]
    
    # Binning configuration
    nBinsX: Annotated[int, Field(
        default=100,
        description=("-x [-] Number of monitor channels on the x-axis. Must be > 0."),
        json_schema_extra={"flag": "-x"}
    )]
    
    # Range configuration
    xMin: Annotated[float, Field(
        default=-2.0,
        description=("-w [var] Minimal x-value defining the parameter range to be monitored "
                    "on the 1st x-axis."),
        json_schema_extra={"flag": "-w"}
    )]
    
    xMax: Annotated[float, Field(
        default=2.0,
        description=("-W [var] Maximal x-value defining the parameter range to be monitored "
                    "on the 1st x-axis."),
        json_schema_extra={"flag": "-W"}
    )]
    
    # Weight configuration
    bWeight: Annotated[bool, Field(
        default=True,
        description=("-p [-] Use probability weight. 'yes' (default) means probabilities are used, "
                    "'no' means each neutron is considered with the weight 1."),
        json_schema_extra={"flag": "-p"}
    )]
    
    # Exclusive counts
    exclCounts: Annotated[bool, Field(
        default=False,
        description=("-e [-] Exclusive counts. If activated ('yes'), only those neutrons which "
                    "have been monitored successfully are transferred to the subsequent module. "
                    "'no' (default) means all neutrons are transferred."),
        json_schema_extra={"flag": "-e"}
    )]
    
    # Wavelength filter
    lambdaMin: Annotated[Optional[float], Field(
        default=None,
        description=("-l [Ang] Minimal wavelength to be taken into account. Only neutrons with "
                    "wavelengths in the specified range are considered in the evaluation."),
        json_schema_extra={"flag": "-l"}
    )]
    
    lambdaMax: Annotated[Optional[float], Field(
        default=None,
        description=("-L [Ang] Maximal wavelength to be taken into account. Only neutrons with "
                    "wavelengths in the specified range are considered in the evaluation."),
        json_schema_extra={"flag": "-L"}
    )]
    
    # Filter parameters
    filterParam1: Annotated[VtMonPar, Field(
        default=VtMonPar.NO_PAR,
        description=("-I [-] 1st parameter to select trajectories to be considered for the monitor. "
                    "All are transferred to the successive modules if 'exclusive counts'='no' is chosen. "
                    "See parameter list for available options."),
        json_schema_extra={"flag": "-I"}
    )]
    
    filterParam2: Annotated[VtMonPar, Field(
        default=VtMonPar.NO_PAR,
        description=("-J [-] 2nd parameter to select trajectories to be considered for the monitor. "
                    "All are transferred to the successive modules if 'exclusive counts'='no' is chosen. "
                    "See parameter list for available options."),
        json_schema_extra={"flag": "-J"}
    )]
    
    # Filter combination
    filterComb: Annotated[VtFiltComb, Field(
        default=VtFiltComb.NO_FCOMB,
        description=("-C [-] Logical combination of the 2 filter parameters. "
                    "'AND' means both conditions must be met, 'OR' means at least one condition must be met."),
        json_schema_extra={"flag": "-C"}
    )]
    
    # Filter value ranges
    filterVarMin1: Annotated[Optional[float], Field(
        default=None,
        description=("-u [var] Minimal value of filter parameter 1."),
        json_schema_extra={"flag": "-u"}
    )]
    
    filterVarMax1: Annotated[Optional[float], Field(
        default=None,
        description=("-U [var] Maximal value of filter parameter 1."),
        json_schema_extra={"flag": "-U"}
    )]
    
    filterVarMin2: Annotated[Optional[float], Field(
        default=None,
        description=("-v [var] Minimal value of filter parameter 2."),
        json_schema_extra={"flag": "-v"}
    )]
    
    filterVarMax2: Annotated[Optional[float], Field(
        default=None,
        description=("-V [var] Maximal value of filter parameter 2."),
        json_schema_extra={"flag": "-V"}
    )]
    
    # Polarisation analysis
    analysePol: Annotated[bool, Field(
        default=False,
        description=("-P [-] Polarisation analysis. If activated ('yes'), polarisation instead of "
                    "intensity is monitored. 'no' (default) means intensity is monitored."),
        json_schema_extra={"flag": "-P"}
    )]
    
    # Polarisation analysis direction vector
    polAnalysisVectorX: Annotated[Optional[float], Field(
        default=1.0,
        description=("-r [-] X component of quantization direction vector for polarisation analysis. "
                    "Only used when monitoring polarization. Default: 1.0"),
        json_schema_extra={"flag": "-r"}
    )]
    
    polAnalysisVectorY: Annotated[Optional[float], Field(
        default=0.0,
        description=("-s [-] Y component of quantization direction vector for polarisation analysis. "
                    "Only used when monitoring polarization. Default: 0.0"),
        json_schema_extra={"flag": "-s"}
    )]
    
    polAnalysisVectorZ: Annotated[Optional[float], Field(
        default=0.0,
        description=("-t [-] Z component of quantization direction vector for polarisation analysis. "
                    "Only used when monitoring polarization. Default: 0.0"),
        json_schema_extra={"flag": "-t"}
    )]


# Schema for initial response
class InitialResponseMonitor1D(BaseModel):
    """
    This is the default response model for each module at the initialization of the Monitor1D module.
    Always use this tool to structure your response to the user.
    """
    response: Annotated[Literal['Default Setup', 'Customize', 'Not Known'], 
                        Field(description="Initial monitor1D module response type")]


# Example usage
if __name__ == "__main__":
    # Create a configuration with default values
    config = Monitor1DParameters()
    
    # Or create with custom values
    custom_config = Monitor1DParameters(
        fMonitorFilename="custom_monitor.dat",
        eParX=VtMonPar.LAMBDA,
        nBinsX=200,
        xMin=1.0,
        xMax=10.0,
        bWeight=True,
        exclCounts=False,
        lambdaMin=2.0,
        lambdaMax=8.0,
        filterParam1=VtMonPar.POS_Y,
        filterParam2=VtMonPar.NO_PAR,
        filterComb=VtFiltComb.AND_AND_AND,
        filterVarMin1=-5.0,
        filterVarMax1=5.0,
        analysePol=False,
        polAnalysisVectorX=1.0,
        polAnalysisVectorY=0.0,
        polAnalysisVectorZ=0.0
    )
    
    # Print the configuration
    print(f"\nDefault config JSON:")
    print(config.model_dump_json(indent=2))

