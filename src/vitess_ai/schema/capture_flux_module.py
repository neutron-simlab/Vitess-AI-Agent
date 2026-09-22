from typing import Annotated
from pydantic import Field, model_validator
from vitess_ai.schema.base import VitessParameterModel, VtWindowType


class CaptureFluxParameters(VitessParameterModel):
    """Configuration model for the capture_flux module (capture_flux.c).

    capture_flux sums the gold-foil capture flux, the integral of phi(lambda)
    weighted by lambda / lambda_ref, over the neutrons hitting the foil, and
    passes every neutron on unchanged.
    """

    ReferenceWavelength: Annotated[float, Field(
        default=1.798,
        ge=0,
        description=("-R [Ang] Reference wavelength lambda_ref in the capture flux definition, "
                    "usually 1.798 Ang. 0.0 means no reference wavelength: the plain "
                    "intensity is summed without the lambda / lambda_ref weight."),
        json_schema_extra={"flag": "-R"}
    )]

    WindowType: Annotated[VtWindowType, Field(
        default=VtWindowType.NO_RESTRICTIONS,
        description=("-t [-] Shape of the gold foil: NO_RESTRICTIONS (every neutron is counted "
                    "and the area is taken as 1 cm^2), CIRCULAR or RECTANGULAR."),
        json_schema_extra={"flag": "-t"}
    )]

    winradius: Annotated[float, Field(
        default=0.0,
        ge=0,
        description="-r [cm] Radius of a circular foil.",
        json_schema_extra={"flag": "-r"}
    )]

    ywincenter: Annotated[float, Field(
        default=0.0,
        description="-y [cm] Horizontal (y) centre of a circular foil.",
        json_schema_extra={"flag": "-y"}
    )]

    zwincenter: Annotated[float, Field(
        default=0.0,
        description="-z [cm] Vertical (z) centre of a circular foil.",
        json_schema_extra={"flag": "-z"}
    )]

    widthmin: Annotated[float, Field(
        default=0.0,
        description="-w [cm] Minimal (right) y value of a rectangular foil.",
        json_schema_extra={"flag": "-w"}
    )]

    widthmax: Annotated[float, Field(
        default=0.0,
        description="-W [cm] Maximal (left) y value of a rectangular foil.",
        json_schema_extra={"flag": "-W"}
    )]

    heightmin: Annotated[float, Field(
        default=0.0,
        description="-h [cm] Minimal (bottom) z value of a rectangular foil.",
        json_schema_extra={"flag": "-h"}
    )]

    heightmax: Annotated[float, Field(
        default=0.0,
        description="-H [cm] Maximal (top) z value of a rectangular foil.",
        json_schema_extra={"flag": "-H"}
    )]

    lambdamin: Annotated[float, Field(
        default=0.0,
        ge=0,
        description=("-l [Ang] Minimal wavelength counted. The wavelength window applies only "
                    "when lambdamin and lambdamax are both non-zero."),
        json_schema_extra={"flag": "-l"}
    )]

    lambdamax: Annotated[float, Field(
        default=0.0,
        ge=0,
        description=("-L [Ang] Maximal wavelength counted. The wavelength window applies only "
                    "when lambdamin and lambdamax are both non-zero."),
        json_schema_extra={"flag": "-L"}
    )]

    @model_validator(mode="after")
    def the_foil_matches_its_shape(self) -> "CaptureFluxParameters":
        """Refuse a foil capture_flux would measure wrongly without complaint.

        The flux is the captured intensity divided by the foil area, which
        capture_flux.c:248-255 computes as pi * winradius^2 or
        (widthmax - widthmin) * (heightmax - heightmin). A zero radius or an
        empty rectangle makes that area 0 or negative, and the run still exits
        0 with an infinite or negative flux.

        The geometry of the other shape is ignored (c:91-102), and with
        NO_RESTRICTIONS all of it is, while the flux is divided by an assumed
        1 cm^2. A radius set next to NO_RESTRICTIONS is a foil the user asked
        for and would not get, so it is refused rather than dropped.
        """
        circle = {
            "winradius": self.winradius,
            "ywincenter": self.ywincenter,
            "zwincenter": self.zwincenter,
        }
        rectangle = {
            "widthmin": self.widthmin,
            "widthmax": self.widthmax,
            "heightmin": self.heightmin,
            "heightmax": self.heightmax,
        }

        if self.WindowType == VtWindowType.CIRCULAR:
            if self.winradius <= 0:
                raise ValueError(
                    "a CIRCULAR foil needs winradius greater than 0; a radius of 0 "
                    "gives an area of 0 and an infinite capture flux"
                )
            ignored = rectangle
        elif self.WindowType == VtWindowType.RECTANGULAR:
            if self.widthmin >= self.widthmax:
                raise ValueError("a RECTANGULAR foil needs widthmin smaller than widthmax")
            if self.heightmin >= self.heightmax:
                raise ValueError("a RECTANGULAR foil needs heightmin smaller than heightmax")
            ignored = circle
        else:
            ignored = {**circle, **rectangle}

        set_but_ignored = [name for name, value in ignored.items() if value != 0.0]
        if set_but_ignored:
            raise ValueError(
                f"{', '.join(set_but_ignored)} would be ignored with WindowType "
                f"{self.WindowType.name}; set them to 0 or choose the shape they belong to"
            )
        return self

    @model_validator(mode="after")
    def the_wavelength_window_is_complete(self) -> "CaptureFluxParameters":
        """capture_flux.c:104-107 applies the window only when both bounds are non-zero.

        One bound alone is therefore not a half-open window but no window at
        all, and the run counts every wavelength without saying so.
        """
        if (self.lambdamin == 0.0) != (self.lambdamax == 0.0):
            raise ValueError(
                "lambdamin and lambdamax must both be set or both be 0; capture_flux "
                "ignores a wavelength window with only one bound"
            )
        if self.lambdamin != 0.0 and self.lambdamin >= self.lambdamax:
            raise ValueError("lambdamin must be smaller than lambdamax")
        return self
