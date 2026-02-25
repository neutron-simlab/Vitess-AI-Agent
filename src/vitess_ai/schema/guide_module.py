from typing import Annotated, Literal
from pydantic import BaseModel, Field
from vitess_ai.schema.base import VtGdeShape


class GuideParameters(BaseModel):
    """Configuration model for neutron guide parameters."""
    
    # Guide shape configuration
    eGuideShapeY: Annotated[VtGdeShape, Field(
        default=VtGdeShape.VT_CONSTANT,
        description=("-Y [-] Shape of the guide in horizontal direction. "
                    "VT_CONSTANT (0): Same cross-section on whole length (usually 1 piece). "
                    "VT_LINEAR (1): Linearly converging/diverging between entrance and exit (usually 1 piece). "
                    "VT_CURVED (2): Several pieces form part of regular polygon (horizontal plane only), requires radius and number of pieces. "
                    "VT_PARABOLIC (3): Several straight pieces approach parabola defined by entrance/exit width, requires number of pieces. "
                    "VT_ELLIPTIC (4): Several straight pieces approach ellipse defined by entrance/exit width and angle, requires angle and number of pieces. "
                    "VT_FROM_FILE (5): Several pieces with different lengths/coatings from file. "
                    "VT_LIN_CURV (6): Same as curved but with different entrance/exit widths (horizontal plane only)."),
        json_schema_extra={"flag": "-Y"}
    )]
    
    eGuideShapeZ: Annotated[VtGdeShape, Field(
        default=VtGdeShape.VT_CONSTANT,
        description=("-Z [-] Shape of the guide in vertical direction. "
                    "VT_CONSTANT (0): Same cross-section on whole length (usually 1 piece). "
                    "VT_LINEAR (1): Linearly converging/diverging between entrance and exit (usually 1 piece). "
                    "VT_CURVED (2): Several pieces form part of regular polygon (horizontal plane only), requires radius and number of pieces. "
                    "VT_PARABOLIC (3): Several straight pieces approach parabola defined by entrance/exit height, requires number of pieces. "
                    "VT_ELLIPTIC (4): Several straight pieces approach ellipse defined by entrance/exit height and angle, requires angle and number of pieces. "
                    "VT_FROM_FILE (5): Several pieces with different lengths/coatings from file. "
                    "VT_LIN_CURV (6): Same as curved but with different entrance/exit heights (horizontal plane only)."),
        json_schema_extra={"flag": "-Z"}
    )]
    
    # File configuration
    ShapeFileName: Annotated[str, Field(
        default="",
        description=("-S [-] Name of the file containing the sizes of the guide, output or input file. "
                    "Optional: used for VT_FROM_FILE shape type where each piece is described by one line in the file "
                    "with parameters: Position, width and height of the beginning of the piece, "
                    "reflectivity files for left, right, top and bottom plane. When empty, -S is omitted in CLI (default configuration)."),
        json_schema_extra={"flag": "-S"}
    )]
    
    # Guide piece configuration
    nPieces: Annotated[int, Field(
        default=1,
        description=("-N [-] Number of guide pieces. "
                    "For VT_CONSTANT and VT_LINEAR usually 1 piece. "
                    "For VT_CURVED, VT_PARABOLIC, VT_ELLIPTIC, and VT_LIN_CURV multiple pieces are required "
                    "to approximate the curved geometry."),
        json_schema_extra={"flag": "-N"}
    )]
    
    # Entrance dimensions
    GuideEntrWidth: Annotated[float, Field(
        default=3.0,
        description="-w [cm] Width of the guide entrance",
        json_schema_extra={"flag": "-w"}
    )]
    
    GuideEntrHeight: Annotated[float, Field(
        default=3.0,
        description="-h [cm] Height of the guide entrance",
        json_schema_extra={"flag": "-h"}
    )]
    
    # Exit dimensions
    GuideExitWidth: Annotated[float, Field(
        default=3.0,
        description="-W [cm] Width of the guide exit",
        json_schema_extra={"flag": "-W"}
    )]
    
    GuideExitHeight: Annotated[float, Field(
        default=3.0,
        description="-H [cm] Height of the guide exit",
        json_schema_extra={"flag": "-H"}
    )]
    
    # Physical parameters
    piecelength: Annotated[float, Field(
        default=50.0,
        description=("-p [cm] Length of 1 piece of the guide. "
                    "For multi-piece guides (curved, parabolic, elliptic), this is the length of each "
                    "individual straight segment that approximates the overall shape."),
        json_schema_extra={"flag": "-p"}
    )]
    
    Radius: Annotated[float, Field(
        default=0.0,
        description=("-R [m] Radius of a guide that is curved (in horizontal plane). "
                    "Used for VT_CURVED and VT_LIN_CURV shapes where several pieces form part of a regular polygon. "
                    "The radius defines the circle through the polygon corners. Set to 0.0 for straight guides."),
        json_schema_extra={"flag": "-R"}
    )]
    
    # Focal point positions (for elliptic shape)
    D_Foc2Y: Annotated[float, Field(
        default=0.0,
        description=("-f [cm] Position behind guide of 2nd focal point in horizontal direction (for elliptic shape). "
                    "Used with VT_ELLIPTIC shape type to define the ellipse geometry along with entrance/exit dimensions."),
        json_schema_extra={"flag": "-f"}
    )]
    
    D_Foc2Z: Annotated[float, Field(
        default=0.0,
        description=("-F [cm] Position behind guide of 2nd focal point in vertical direction (for elliptic shape). "
                    "Used with VT_ELLIPTIC shape type to define the ellipse geometry along with entrance/exit dimensions."),
        json_schema_extra={"flag": "-F"}
    )]
    
    # M-values for different walls
    MValGenL: Annotated[float, Field(
        default=3.0,
        description="-L [-] M-value for left wall",
        json_schema_extra={"flag": "-L"}
    )]
    
    MValGenR: Annotated[float, Field(
        default=3.0,
        description="-Q [-] M-value for right wall",
        json_schema_extra={"flag": "-Q"}
    )]
    
    MValGenTB: Annotated[float, Field(
        default=3.0,
        description="-G [-] M-value for top and bottom wall",
        json_schema_extra={"flag": "-G"}
    )]


# Schema for initial response
class InitialResponseGuide(BaseModel):
    """
    This is the default response model for each module at the initialization of the Guide module.
    Always use this tool to structure your response to the user.
    """
    response: Annotated[Literal['Default Setup', 'Customize', 'Not Known'], 
                        Field(description="Initial guide module response type")]



# Example usage
if __name__ == "__main__":
    # Create a configuration with default values
    config = GuideParameters()
    
    # Or create with custom values
    custom_config = GuideParameters(
        eGuideShapeY=VtGdeShape.VT_LINEAR,
        eGuideShapeZ=VtGdeShape.VT_CURVED,
        ShapeFileName="custom_guide.dat",
        nPieces=5,
        GuideEntrWidth=2.5,
        GuideEntrHeight=3.0,
        GuideExitWidth=2.0,
        GuideExitHeight=2.5,
        piecelength=50.0,
        Radius=1000.0,
        D_Foc2Y=100.0,
        D_Foc2Z=150.0,
        MValGenL=2.0,
        MValGenR=2.0,
        MValGenTB=1.5
    )
    
    # Print the configuration
    print(f"\nDefault config JSON:")
    print(config.model_dump_json(indent=2))