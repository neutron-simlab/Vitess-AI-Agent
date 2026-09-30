from typing import Annotated
from pydantic import Field, model_validator
from vitess_ai.schema.base import VitessParameterModel, VtDetGeom, VtFormat2D


class ScreenParameters(VitessParameterModel):
    """Configuration model for the screen module (screen.c).

    An ideal detector surface, flat or cylindrical. Each neutron is moved on to
    the surface, and its weight is added to the pixel it hits; the module writes
    that 2D image itself, so no monitor is needed after it. A neutron that
    misses the surface is not passed on.

    Field names are the C globals.

    The defaults are the VITESS GUI's (yaml/3.8/modules/screen.yaml), not the C
    initialisers, which do not run: no geometry stops the module, and a screen
    of width, height and distance 0 is hit by nothing. There is no shipped
    default file for this module. Two GUI values are changed, each explained in
    its field: the file name and the number of pixels.

    With these defaults the screen is 10 x 10 cm, 1 m from the frame origin.
    Measured on the app's default pipeline with its 100 000-trajectory beam: every
    neutron reaches it, from the guide exit (within +-2.9 cm) and after VITESS's
    default sample (within +-3.3 cm).

    Line references are to screen.c at VITESS 6bd0e006. Every rule below was
    measured on that binary with VITESS's own module tests Screen-1_Flat and
    Screen-2_Cylinder, whose commands reproduce VITESS's reference outputs
    exactly.
    """

    OutFileName: Annotated[str, Field(
        default="screen.dat",
        min_length=1,
        description=("-O [-] Name of the file the 2D image is written to. Without it the "
                    "module writes no image and still exits 0. The VITESS GUI suggests "
                    "'screen.pos'; '.dat' is used here because the chat delivers .dat "
                    "files and not .pos, and it matches 'monitor2D.dat'."),
        json_schema_extra={"flag": "-O"}
    )]

    eGeom: Annotated[VtDetGeom, Field(
        default=VtDetGeom.VT_DET_FLAT,
        description=("-G [-] Shape of the screen: VT_DET_FLAT (2), a rectangle across the "
                    "beam, or VT_DET_CYL (1), an upright cylinder around the frame origin."),
        json_schema_extra={"flag": "-G"}
    )]

    eFormat: Annotated[VtFormat2D, Field(
        default=VtFormat2D.XYZ,
        description=("-F [-] File format of the image: MATRIX (0), XYZ (1), MATR_CMPT (2), "
                    "XYZ_CMPT (3) or MATR_INT (4, detector counts instead of n/s). The "
                    "xyz layouts keep each pixel's error and trajectory count."),
        json_schema_extra={"flag": "-F"}
    )]

    Width: Annotated[float, Field(
        default=10.0,
        ge=0,
        description=("-w [cm] Full width (horizontal, y) of a flat screen, centred on the "
                    "beam axis. Not used by a cylindrical screen."),
        json_schema_extra={"flag": "-w"}
    )]

    Height: Annotated[float, Field(
        default=10.0,
        gt=0,
        description=("-h [cm] Full height (vertical, z) of the screen, centred on the beam "
                    "axis, for both shapes."),
        json_schema_extra={"flag": "-h"}
    )]

    AngleMin: Annotated[float, Field(
        default=-175.0,
        description=("-a [deg] Lower limit of the horizontal angle a cylindrical screen "
                    "covers, measured from the x axis; -180 to 180. Not used by a flat "
                    "screen."),
        json_schema_extra={"flag": "-a"}
    )]

    AngleMax: Annotated[float, Field(
        default=175.0,
        description=("-A [deg] Upper limit of the horizontal angle a cylindrical screen "
                    "covers; -180 to 180, greater than AngleMin. Not used by a flat screen."),
        json_schema_extra={"flag": "-A"}
    )]

    Distance: Annotated[float, Field(
        default=100.0,
        gt=0,
        description=("-D [cm] Distance from the frame origin -- the sample centre after the "
                    "sample, the guide exit without one -- to a flat screen along x, or "
                    "the radius of a cylindrical screen."),
        json_schema_extra={"flag": "-D"}
    )]

    nBinsY: Annotated[int, Field(
        default=50,
        gt=0,
        description=("-y [-] Number of pixels across: over the width of a flat screen, or "
                    "over the angle range of a cylindrical one. The VITESS GUI suggests 1, "
                    "which is a single pixel and no image; 50 gives 0.2 cm pixels on the "
                    "default screen, as in VITESS's own test Screen-1."),
        json_schema_extra={"flag": "-y"}
    )]

    nBinsZ: Annotated[int, Field(
        default=50,
        gt=0,
        description=("-z [-] Number of pixels over the height. The VITESS GUI suggests 1; "
                    "50 for the reason given on nBinsY."),
        json_schema_extra={"flag": "-z"}
    )]

    @model_validator(mode="after")
    def the_screen_has_a_shape_and_a_format(self) -> "ScreenParameters":
        """c:266-267 stops the module for any geometry but 1 and 2.

        Measured: -G0 (the C default), -G3 and -G-1 each exit 255 with "Wrong
        value for geometry of the screen", after the module before has already
        run. -F-1 and -F5 exit 255 with "value for variable 'eFormat' unknown".
        """
        if self.eGeom == VtDetGeom.VT_NO_DET_GEOM:
            raise ValueError(
                "eGeom must be VT_DET_FLAT (2) or VT_DET_CYL (1); VT_NO_DET_GEOM stops "
                "the module"
            )
        if self.eFormat == VtFormat2D.NO_2D_FORMAT:
            raise ValueError(
                "eFormat must be one of the VITESS 2D formats; NO_2D_FORMAT (-1) stops "
                "the module"
            )
        return self

    @model_validator(mode="after")
    def the_screen_can_be_hit(self) -> "ScreenParameters":
        """Refuse a screen no neutron reaches, or one VITESS reaches the wrong way.

        c:118 counts a neutron on a flat screen when |y| < Width/2 and |z| <
        Height/2; c:154 on a cylinder when its angle lies in (AngleMin, AngleMax).
        Measured with test 1 (flat, 578 trajectories on the screen) and test 2
        (cylinder, 2732):

        ==============================  ======================================
        Width 0 or -50 (flat)           nothing on the screen, nothing passed on
        Height 0 or -50                 the same, for both shapes
        Distance -1000 (flat)           578 again: the plane behind the origin
                                        catches the beam as if it flew backwards
        Distance 0 (flat)               908: the plane through the origin
        Distance 0 (cylinder)           10702 trajectories, 4.5x the intensity
        Distance -100 (cylinder)        identical to +100
        AngleMin = AngleMax = 10        nothing on the screen
        AngleMin 30, AngleMax -30       nothing on the screen
        AngleMin 0, AngleMax 360        1400 of 2732: every angle between -180
                                        and 0 is lost, because VITESS measures
                                        the angle as atan2, from -180 to 180
        ==============================  ======================================

        Height and Distance are refused below or at 0 by their fields.
        """
        if self.eGeom == VtDetGeom.VT_DET_FLAT and self.Width <= 0:
            raise ValueError(
                "a flat screen needs Width greater than 0; with 0 no neutron hits it"
            )
        if self.eGeom == VtDetGeom.VT_DET_CYL:
            if not -180 <= self.AngleMin < self.AngleMax <= 180:
                raise ValueError(
                    "a cylindrical screen needs -180 <= AngleMin < AngleMax <= 180; "
                    "VITESS measures the angle from -180 to 180, so 0 to 360 silently "
                    "loses every neutron between -180 and 0, and an empty or reversed "
                    "range catches nothing"
                )
        return self

    @model_validator(mode="after")
    def no_value_is_ignored(self) -> "ScreenParameters":
        """A flat screen reads no angles and a cylinder no width.

        Measured: test 1 with -a-30 -A30, and test 2 with -w50, are identical to
        the runs without them. A value the user gave and would not get is
        refused, as in capture_flux and the sample. An ignored value left at 0 or
        at its default was not asked for, so it passes.
        """
        ignored = {
            VtDetGeom.VT_DET_FLAT: ("AngleMin", "AngleMax"),
            VtDetGeom.VT_DET_CYL: ("Width",),
        }.get(self.eGeom, ())
        fields = type(self).model_fields
        set_but_ignored = [
            name for name in ignored
            if getattr(self, name) not in (0.0, fields[name].default)
        ]
        if set_but_ignored:
            raise ValueError(
                f"{', '.join(set_but_ignored)} would be ignored for a {self.eGeom.name} "
                "screen; set them to 0 or choose the shape they belong to"
            )
        return self
