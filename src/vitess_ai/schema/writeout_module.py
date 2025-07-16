from typing import Annotated, Optional, Literal
from pydantic import BaseModel, Field
from vitess_ai.schema.base import VtDataFormat, VtPrgFormat, VtSeparator, VtTrace


class VtOutputFlags(BaseModel):
    """Flags to determine which neutron parameters are written to output."""
    
    bF_cID: Annotated[bool, Field(
        default=True,
        description="-c [-] Flag to write neutron ID to output"
    )]
    
    bF_cTrc: Annotated[bool, Field(
        default=True,
        description="-c [-] Flag to write trace flag to output"
    )]
    
    bF_cColor: Annotated[bool, Field(
        default=True,
        description="-c [-] Flag to write neutron color to output"
    )]
    
    bF_cTOF: Annotated[bool, Field(
        default=True,
        description="-c [-] Flag to write time-of-flight to output"
    )]
    
    bF_cLambda: Annotated[bool, Field(
        default=True,
        description="-c [-] Flag to write wavelength to output"
    )]
    
    bF_cCounts: Annotated[bool, Field(
        default=True,
        description="-c [-] Flag to write intensity/counts to output"
    )]
    
    bF_cPosition: Annotated[bool, Field(
        default=True,
        description="-c [-] Flag to write position coordinates to output"
    )]
    
    bF_cDirection: Annotated[bool, Field(
        default=True,
        description="-c [-] Flag to write direction vectors to output"
    )]
    
    bF_cSpin: Annotated[bool, Field(
        default=True,
        description="-c [-] Flag to write spin state to output"
    )]


class VtFilterLimits(BaseModel):
    """Filtering limits for neutron selection based on physical parameters."""
    
    # Wavelength filtering
    filtLambdaMin: Annotated[float, Field(
        default=-1.0,
        description="-l [Ang] Minimal wavelength to be taken into account"
    )]
    
    filtLambdaMax: Annotated[float, Field(
        default=1.0e10,
        description="-L [Ang] Maximal wavelength to be taken into account"
    )]
    
    # Position filtering
    filtYMin: Annotated[float, Field(
        default=-1.0e10,
        description="-y [cm] Minimal horizontal position to be taken into account"
    )]
    
    filtYMax: Annotated[float, Field(
        default=1.0e10,
        description="-Y [cm] Maximal horizontal position to be taken into account"
    )]
    
    filtZMin: Annotated[float, Field(
        default=-1.0e10,
        description="-z [cm] Minimal vertical position to be taken into account"
    )]
    
    filtZMax: Annotated[float, Field(
        default=1.0e10,
        description="-Z [cm] Maximal vertical position to be taken into account"
    )]
    
    # Divergence filtering
    filtYDivMin: Annotated[float, Field(
        default=-1.0e10,
        description="-e [deg] Minimal horizontal divergence to be taken into account"
    )]
    
    filtYDivMax: Annotated[float, Field(
        default=1.0e10,
        description="-d [deg] Maximal horizontal divergence to be taken into account"
    )]
    
    filtZDivMin: Annotated[float, Field(
        default=-1.0e10,
        description="-E [deg] Minimal vertical divergence to be taken into account"
    )]
    
    filtZDivMax: Annotated[float, Field(
        default=1.0e10,
        description="-D [deg] Maximal vertical divergence to be taken into account"
    )]
    
    # General divergence filtering
    filtDivMin: Annotated[float, Field(
        default=-1.0e10,
        description="-g [deg] Minimal divergence to be taken into account"
    )]
    
    filtDivMax: Annotated[float, Field(
        default=1.0e10,
        description="-G [deg] Maximal divergence to be taken into account"
    )]


class WriteoutParameters(BaseModel):
    """Main configuration model for neutron transport data processing."""
    
    # Output file configuration
    sOutFileName: Annotated[Optional[str], Field(
        default=None,
        description="-A [-] Output file name"
    )]
    
    # Control flags
    bActive: Annotated[bool, Field(
        default=True,
        description="-a [-] Flag: YES: writeout is active, NO: output file is not written"
    )]
    
    bHeader: Annotated[bool, Field(
        default=True,
        description="-h [-] Flag: YES: write header, NO: write only data, no header"
    )]
    
    # Format configuration
    ePrgFormat: Annotated[VtPrgFormat, Field(
        default=VtPrgFormat.VT_VITESS_FMT,
        description="-f [-] Output format: VT_VITESS_FMT: VITESS format, VT_MCSTAS_FMT: McStas, VT_MCPL_FMT: MCPL, VT_MCNP6_FMT: MCNP6, VT_MCNPX_FMT: MCNPX"
    )]
    
    eDatFormat: Annotated[VtDataFormat, Field(
        default=VtDataFormat.VT_FLOAT,
        description="-F [-] Data format (exponential, float, binary)"
    )]
    
    eSeparator: Annotated[VtSeparator, Field(
        default=VtSeparator.VT_BLANK,
        description="-S [-] Separator between columns (space, tab)"
    )]
    
    # Neutron selection
    iDetectColor: Annotated[int, Field(
        default=-1,
        description="-C [-] Write out only neutrons with a given color, -1 means any"
    )]
    
    # Output parameters control
    output_flags: Annotated[VtOutputFlags, Field(
        description="Flags determining which parameters are written"
    )]
    
    # Normalization and metadata
    FactInt: Annotated[float, Field(
        default=1.0,
        description="-I [-] Factor to normalize to the source intensity from MCNP data"
    )]
    
    iSurface: Annotated[Optional[int], Field(
        default=None,
        description="-s [-] Surface ID written to the event file"
    )]
    
    pTitle: Annotated[Optional[str], Field(
        default=None,
        description="-T [-] Title of the simulation"
    )]
    
    # Filtering limits
    filter_limits: Annotated[VtFilterLimits, Field(
        description="Filtering limits for neutron selection"
    )]

# Schema for initial response
class InitialResponseWriteout(BaseModel): 
    """
    This is the default response model for each module at the initialization of the Writeout module.
    Always use this tool to structure your response to the user.
    """
    response: Annotated[Literal['Default Setup', 'Customize', 'Not Known'], 
                        Field(description="Initial writeout module response type")]

# Example usage
if __name__ == "__main__":
    # Create a configuration with default values
    config = WriteoutParameters()
    
    # Or create with custom values
    
    custom_config = WriteoutParameters(
        sOutFileName="neutron_data.out",
        ePrgFormat=VtPrgFormat.VT_MCSTAS_FMT,
        eDatFormat=VtDataFormat.VT_BINARY,
        iDetectColor=1,
        FactInt=2.5,
        pTitle="My Neutron Simulation",
        output_flags=VtOutputFlags(
            bF_cID=True,
            bF_cTrc=False,
            bF_cColor=True
        ),
        filter_limits=VtFilterLimits(
            filtLambdaMin=0.5,
            filtLambdaMax=10.0,
            filtYMin=-5.0,
            filtYMax=5.0
        )
    )
    
    # Print the configuration
    print(config.model_dump_json(indent=2))