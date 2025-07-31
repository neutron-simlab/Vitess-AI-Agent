from pydantic import BaseModel, Field
from typing import Annotated, Union, Literal, List
from annotated_types import Len

# class VtMonPar(Enum):
    # NO_PAR = 0
    # POS_X = 17
    # POS_Y = 1
    # POS_Z = 2
    # DIV_Y = 3
    # DIV_Z = 4
    # LAMBDA = 5
    # ENERGY = 6
    # TIME = 7
    # K_Y = 8
    # K_Z = 9
    # POS_R = 10
    # POS_PHI = 11
    # POS_THETA = 18
    # DIR_PHI = 15
    # DIR_THETA = 16
    # COL_VERT = 12
    # COL_HOR = 13
    # COLOR = 14

class NO_PAR(BaseModel): 
    """
    This is the model for 'no parameter' on filter module.
    """
    val:int = Field(description="Value according to enumerate in Vitess filter parameter", default=0) 

class POS_X(BaseModel): 
    """
    This is the filter parameter type model for the x-coordinate of the position of the neutron at the entrance of the module.
    """
    val:int = Field(description="Value according to enumerate in Vitess filter parameter", default=17)
    min_val:float = Field(description="Minimum value of x position.")
    max_val:float = Field(description="Maximum value of x position.")

class POS_Y(BaseModel):
    """
    This is the filter parameter type model for the y-coordinate of the position of the neutron at the entrance of the module.
    """
    val:int = Field(description="Value according to enumerate in Vitess filter parameter", default=1)
    min_val:float = Field(description="Minimum value of x position.")
    max_val:float = Field(description="Minimum value of x position.")

class POS_Z(BaseModel): 
    """
    This is the filter parameter type model for the z-coordinate of the position of the neutron at the entrance of the module.
    """
    val:int = Field(description="Value according to enumerate in Vitess filter parameter", default=2)
    min_val:float = Field(description="Minimum value of z position.")
    max_val:float = Field(description="Maximum value of z position.")

class DIV_Y(BaseModel): 
    """
    This is the filter parameter type model for horizontal components of the direction of the neutron at the entrance of the module.
    """
    val:int = Field(description="Value according to enumerate in Vitess filter parameter", default=3)
    min_val:float = Field(description="Minimum value of y division.")
    max_val:float = Field(description="Maximum value of y division.")

class DIV_Z(BaseModel): 
    """
    This is the filter parameter type model for vertical components of the direction of the neutron at the entrance of the module.
    """
    val:int = Field(description="Value according to enumerate in Vitess filter parameter", default=4)
    min_val:float = Field(description="Minimum value of z division.")
    max_val:float = Field(description="Maximum value of z division.")

class LAMBDA(BaseModel): 
    """
    This is the filter parameter type model for neutron wavelength.
    """
    val:int = Field(description="Value according to enumerate in Vitess filter parameter", default=5)
    min_val:float = Field(description="Minimum value of lambda.")
    max_val:float = Field(description="Maximum value of lambda.")

class ENERGY(BaseModel):
    """
    This is the filter parameter type model for the neutron energy.
    """
    val:int = Field(description="Value according to enumerate in Vitess filter parameter", default=6)
    min_val:float = Field(description="Minimum value of energy.")
    max_val:float = Field(description="Maximum value of energy.")

class TIME(BaseModel): 
    """
    This is the filter parameter type model for the  neutron time measured since the generation at the source.
    """
    val:int = Field(description="Value according to enumerate in Vitess filter parameter", default=7)
    min_val:float = Field(description="Minimum value of time.")
    max_val:float = Field(description="Maximum value of time.")

class K_Y(BaseModel): 
    """
    This is the filter parameter type model for the y-component of the neutron wave vector.
    """
    val:int = Field(description="Value according to enumerate in Vitess filter parameter", default=8)
    min_val:float = Field(description="Minimum value of the y-component of the neutron wave vector.")
    max_val:float = Field(description="Maximum value of the y-component of the neutron wave vector.")


class K_Z(BaseModel): 
    """
    This is the filter parameter type model for the z-component of the neutron wave vector.
    """
    val:int = Field(description="Value according to enumerate in Vitess filter parameter", default=9)
    min_val:float = Field(description="Minimum value of the z-component of the neutron wave vector.")
    max_val:float = Field(description="Maximum value of the z-component of the neutron wave vector.")

class POS_R(BaseModel): 
    """
    This is the filter parameter type model for the projection of the neutron vector on the y-z plane.
    """
    val:int = Field(description="Value according to enumerate in Vitess filter parameter", default=10)
    min_val:float = Field(description="Minimum radial position.")
    max_val:float = Field(description="Maximum radial position.")

class POS_PHI(BaseModel): 
    """
    This the filter parameter type model for the phi angle of the r-phi cylindrical coordinate system corresponding to the y-z plane.
    """
    val:int = Field(description="Value according to enumerate in Vitess filter parameter", default=11)
    min_val:float = Field(description="Minimum value of phi position.")
    max_val:float = Field(description="Maximum value of phi position.")


class DIR_PHI(BaseModel): 
    """
    This the model for representing directional parameters that describe the orientation of a neutron’s direction vector in spherical coordinates.
    Given a neutron’s direction as a 3D unit vector: (x0, y0, z0)
    DIR_PHI is the Azimuthal angle phi in degrees, calculated as atan2(z0, y0)
    """
    val:int = Field(description="Value according to enumerate in Vitess filter parameter", default=15)
    min_val:float = Field(description="Minimum value of phi direction.")
    max_val:float = Field(description="Maximum value of phi direction.")


class DIR_THETA(BaseModel): 
    """
    This the model for representing directional parameters that describe the orientation of a neutron’s direction vector in spherical coordinates.
    Given a neutron’s direction as a 3D unit vector: (x0, y0, z0)
    DIR_THETA is the polar angle theta in degrees, calculated as acos(x0)
    """
    val:int = Field(description="Value according to enumerate in Vitess filter parameter", default=16)
    min_val:float = Field(description="Minimum value of theta direction.")
    max_val:float = Field(description="Maximum value of theta direction.")

class COL_VERT(BaseModel): 
    """
    This is the filter parameter type model for the number of reflections at top or bottom plane.
    """
    val:int = Field(description="Value according to enumerate in Vitess filter parameter", default=12)
    min_val:float = Field(description="Minimum vertical color value.")
    max_val:float = Field(description="Maximum vertical color value.")

class COL_HOR(BaseModel): 
    """
    This is the filter parameter type model for the number of reflections at left or right plane.
    """
    val:int = Field(description="Value according to enumerate in Vitess filter parameter", default=13)
    min_val:float = Field(description="Minimum horizontal color value.")
    max_val:float = Field(description="Maximum horizontal color value.")

class COLOR(BaseModel): 
    """
    This is filter parameter type model for the number of total reflections, including reflections at top or bottom plane and at left or right plane, i.e., COL_VERT + COL_HOR.
    """
    val:int = Field(description="Value according to enumerate in Vitess filter parameter", default=14)
    min_val:float = Field(description="Minimum color value.")
    max_val:float = Field(description="Maximum color value.")

# -----------------------
# Union type for all
# -----------------------
FilterParameterType = Union[
    NO_PAR,
    POS_X,
    POS_Y,
    POS_Z,
    DIV_Y,
    DIV_Z,
    LAMBDA,
    ENERGY,
    TIME,
    K_Y,
    K_Z,
    POS_R,
    POS_PHI,
    DIR_PHI,
    DIR_THETA,
    COL_VERT,
    COL_HOR,
    COLOR
]

class I(BaseModel):
    """
    First parameter model determining which trajectories are kept.
    """
    filter_parameter:FilterParameterType =  NO_PAR()

class J(BaseModel): 
    """
    Second parameter model determining which trajectories are kept.
    """
    filter_parameter:FilterParameterType =  NO_PAR()

class K(BaseModel): 
    """
    Third parameter model determining which trajectories are kept.
    """
    filter_parameter:FilterParameterType =  NO_PAR() 

class L(BaseModel): 
    """
    Fourth parameter model determining which trajectories are kept.
    """
    filter_parameter:FilterParameterType =  NO_PAR()

class FilterParameterSet(BaseModel):
    """
    A set of filter parameter with maximum of 4 member and they have a logical connector, e.g., AND, OR, and AND_OR
    """
    FilterSet:Annotated[List[FilterParameterType], Len(min_length=4, max_length=4)]
    connector:Literal["AND", "OR", "AND_OR"]

class FilterBlock(BaseModel):
    """
    A collection of multiple FilterParameterSet entries.
    Each entry represents one line (row) of filter logic.
    """
    filters: List[FilterParameterSet]

class InitialResponseFilter(BaseModel): 
    """
    This is the default response model for each module at the initialization of the filter module.
    Always use this tool to structure your response to the user.
    """
    response: Annotated[Literal['Default Setup', 'Customize', 'Not Known'], 
                        Field(description="Initial filter module response type")]