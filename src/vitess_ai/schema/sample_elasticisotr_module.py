from typing import Annotated, Any
from pydantic import Field, model_validator
from vitess_ai.schema.base import VitessParameterModel, VtSmplGeom


class SampleElasticIsotrParameters(VitessParameterModel):
    """Configuration model for the sample_elasticisotr module (sample_elasticisotr.c).

    An elastic sample that scatters isotropically into a band of directions
    around a mean direction. Every neutron that hits it is scattered -- there
    is no unscattered beam -- and its weight is multiplied by the scattering
    probability, the absorption along its path and the solid angle fraction.

    Field names are the C globals; the components of a C vector carry X/Y/Z
    or the file's own Hor/Vert. Defaults are the C initialisers, which do not
    run on their own: with no geometry the module stops, and with no
    scattering coefficient or range every neutron gets weight 0. A runnable
    starting point is `SHIPPED_DEFAULT` below.

    Line references are to sample_elasticisotr.c at VITESS 6bd0e006. Every
    rule below was measured on that binary with VITESS's own module test 1
    (1000 trajectories, GSL seed 1), run once from its parameter file and once
    from these flags: the two outputs, and VITESS's reference output, are
    identical.
    """

    pSmplFileName: Annotated[str, Field(
        default="sampleelastizotr_default.iso",
        min_length=1,
        description=("-P [-] Name of the sample parameter file. The module refuses to start "
                    "without one (c:501), but no such file is staged: a missing file only "
                    "logs a warning (c:582), and every value below comes from its flag. "
                    "Leave it at its default."),
        json_schema_extra={"flag": "-P"}
    )]

    Repetition: Annotated[int, Field(
        default=1,
        ge=1,
        description=("-A [-] How many scattered trajectories to make from each incoming one, "
                    "for better statistics; the weight is divided by it. Above 20 VITESS "
                    "warns that the incoming statistics must be very good."),
        json_schema_extra={"flag": "-A"}
    )]

    iColor: Annotated[int, Field(
        default=-1,
        ge=-1,
        description=("-c [-] Only neutrons of this colour are scattered; the others pass "
                    "unchanged. -1 scatters every neutron."),
        json_schema_extra={"flag": "-c"}
    )]

    eGeom: Annotated[VtSmplGeom, Field(
        default=VtSmplGeom.VT_NO_GEOM,
        description=("-G [-] Shape of the sample: VT_CUBE (1), VT_CYL (2), VT_SPHERE (3) or "
                    "VT_HOL_CYL (4). VT_NO_GEOM (0) stops the module."),
        json_schema_extra={"flag": "-G"}
    )]

    ScatMainHor: Annotated[float, Field(
        default=0.0,
        description=("-E [deg] Horizontal angle theta of the mean scattering direction; "
                    "(0, 0) is straight ahead along the incoming beam."),
        json_schema_extra={"flag": "-E"}
    )]

    ScatMainVert: Annotated[float, Field(
        default=0.0,
        description="-F [deg] Vertical angle phi of the mean scattering direction.",
        json_schema_extra={"flag": "-F"}
    )]

    ScatRangeHor: Annotated[float, Field(
        default=0.0,
        ge=0,
        description=("-e [deg] Horizontal HALF-range: neutrons are scattered into "
                    "[theta - e, theta + e]. Greater than 0 and at most 180. A parameter "
                    "file gives the full range instead; on the command line it is half."),
        json_schema_extra={"flag": "-e"}
    )]

    ScatRangeVert: Annotated[float, Field(
        default=0.0,
        ge=0,
        description=("-f [deg] Vertical HALF-range: neutrons are scattered into "
                    "[phi - f, phi + f]. Greater than 0 and less than 90."),
        json_schema_extra={"flag": "-f"}
    )]

    AbsorptionC: Annotated[float, Field(
        default=0.0,
        ge=0,
        description=("-m [1/cm/Ang] Macroscopic absorption cross section per Angstrom of "
                    "wavelength: density x absorption cross section, converted from the "
                    "tabulated 1.798 Ang value to 1 Ang. 0 means no absorption."),
        json_schema_extra={"flag": "-m"}
    )]

    ScatteringC: Annotated[float, Field(
        default=0.0,
        ge=0,
        description=("-T [1/cm] Macroscopic total scattering cross section: density x "
                    "scattering cross section. Must be greater than 0."),
        json_schema_extra={"flag": "-T"}
    )]

    PosSampleX: Annotated[float, Field(
        default=0.0,
        description=("-x [cm] Sample centre along the beam, in the frame of the module "
                    "before (in this pipeline, from the guide exit)."),
        json_schema_extra={"flag": "-x"}
    )]

    PosSampleY: Annotated[float, Field(
        default=0.0,
        description="-y [cm] Horizontal position of the sample centre.",
        json_schema_extra={"flag": "-y"}
    )]

    PosSampleZ: Annotated[float, Field(
        default=0.0,
        description="-z [cm] Vertical position of the sample centre.",
        json_schema_extra={"flag": "-z"}
    )]

    Diameter: Annotated[float, Field(
        default=0.0,
        ge=0,
        description=("-t [cm] Thickness (x) of a cuboid, or the (outer) diameter of a "
                    "cylinder, hollow cylinder or sphere."),
        json_schema_extra={"flag": "-t"}
    )]

    Height: Annotated[float, Field(
        default=0.0,
        ge=0,
        description="-h [cm] Height (z) of a cuboid, cylinder or hollow cylinder; 0 for a sphere.",
        json_schema_extra={"flag": "-h"}
    )]

    Width: Annotated[float, Field(
        default=0.0,
        ge=0,
        description=("-w [cm] Width (y) of a cuboid, or the inner diameter of a hollow "
                    "cylinder; 0 for a cylinder or a sphere."),
        json_schema_extra={"flag": "-w"}
    )]

    AnglSmplHor: Annotated[float, Field(
        default=0.0,
        description=("-o [deg] Sample orientation: rotation about the z axis (first). "
                    "0 for a sphere."),
        json_schema_extra={"flag": "-o"}
    )]

    AnglSmplVert: Annotated[float, Field(
        default=0.0,
        description=("-O [deg] Sample orientation: rotation about the new y axis (second). "
                    "0 for a sphere."),
        json_schema_extra={"flag": "-O"}
    )]

    TranslOutX: Annotated[float, Field(
        default=0.0,
        description=("-X [cm] Origin of the output frame along the beam, in the input frame. "
                    "The modules after the sample measure from here; setting it to the "
                    "sample position puts the origin at the sample."),
        json_schema_extra={"flag": "-X"}
    )]

    TranslOutY: Annotated[float, Field(
        default=0.0,
        description="-Y [cm] Horizontal position of the output frame origin.",
        json_schema_extra={"flag": "-Y"}
    )]

    TranslOutZ: Annotated[float, Field(
        default=0.0,
        description="-Z [cm] Vertical position of the output frame origin.",
        json_schema_extra={"flag": "-Z"}
    )]

    AnglOutHor: Annotated[float, Field(
        default=0.0,
        description=("-u [deg] Output frame rotation about the z axis (first). 0 keeps x "
                    "along the incoming beam."),
        json_schema_extra={"flag": "-u"}
    )]

    AnglOutVert: Annotated[float, Field(
        default=0.0,
        description="-U [deg] Output frame rotation about the new y axis (second).",
        json_schema_extra={"flag": "-U"}
    )]

    @model_validator(mode="after")
    def the_sample_has_a_shape(self) -> "SampleElasticIsotrParameters":
        """c:613-619 stops the module when no geometry is given.

        Measured: sample_elasticisotr exits 255 with "Sample geometry missing!".
        A loud failure, but only once the user has left; refused here instead.
        """
        if self.eGeom == VtSmplGeom.VT_NO_GEOM:
            raise ValueError(
                "eGeom must name a shape: VT_CUBE (1), VT_CYL (2), VT_SPHERE (3) or "
                "VT_HOL_CYL (4); VT_NO_GEOM stops the module"
            )
        return self

    @model_validator(mode="after")
    def the_sample_scatters(self) -> "SampleElasticIsotrParameters":
        """Refuse a scattering coefficient or range that makes every weight 0.

        c:235 multiplies the weight by 1 - exp(-path * ScatteringC), and c:337 by
        ScatRangeHor/90 * sin(ScatRangeVert * pi/90) / 4. Measured, with the
        test sample (ranges 45 and 12.5):

        ====================  =======================================
        ScatteringC 0         nothing written, every module exits 0
        ScatRangeHor 0        nothing written (the log warns)
        ScatRangeHor 180      4x the weight of 45 -- linear, as coded
        ScatRangeHor 270      6x: past 180 the band covers the circle
                              more than once and the weight keeps growing
        ScatRangeVert 89      weight 5.5e5 instead of 6.8e6
        ScatRangeVert 90      weight 1.9e-9: effectively nothing
        ScatRangeVert 120     nothing written: sin() is negative
        ====================  =======================================
        """
        if self.ScatteringC <= 0:
            raise ValueError(
                "ScatteringC must be greater than 0; with 0 no neutron is scattered "
                "and the module passes nothing on"
            )
        if not 0 < self.ScatRangeHor <= 180:
            raise ValueError(
                "ScatRangeHor is a half-range and must be greater than 0 and at most "
                "180 degrees; 0 scatters nothing, and above 180 the band covers the "
                "circle more than once while the weight keeps growing"
            )
        if not 0 < self.ScatRangeVert < 90:
            raise ValueError(
                "ScatRangeVert is a half-range and must be greater than 0 and less than "
                "90 degrees; VITESS weights by sin(2 x ScatRangeVert), which is 0 at 0 "
                "and at 90 and negative beyond"
            )
        return self

    @model_validator(mode="after")
    def the_size_matches_the_shape(self) -> "SampleElasticIsotrParameters":
        """Each shape reads only some sizes (c:638-649); the rest are ignored.

        Measured: a size the shape needs set to 0 means no neutron meets the
        sample, and nothing is written. A hollow cylinder whose inner diameter
        equals the outer one writes nothing; a larger inner diameter writes 1609
        trajectories with *more* weight than the real shell (8.5e6 vs 6.8e6).
        An inner diameter of 0 is simply a solid cylinder, and is allowed.

        A cylinder's width, a sphere's height and width, and a sphere's
        orientation angles change nothing (identical output). A value the user
        gave and would not get is refused, as in capture_flux.
        """
        needed = {
            VtSmplGeom.VT_CUBE: ("Diameter", "Height", "Width"),
            VtSmplGeom.VT_CYL: ("Diameter", "Height"),
            VtSmplGeom.VT_SPHERE: ("Diameter",),
            VtSmplGeom.VT_HOL_CYL: ("Diameter", "Height"),
        }.get(self.eGeom, ())
        missing = [name for name in needed if getattr(self, name) <= 0]
        if missing:
            raise ValueError(
                f"a {self.eGeom.name} sample needs {', '.join(missing)} greater than 0; "
                "with 0 no neutron hits the sample"
            )

        if self.eGeom == VtSmplGeom.VT_HOL_CYL and self.Width >= self.Diameter:
            raise ValueError(
                "a hollow cylinder needs its inner diameter (Width) smaller than its "
                "outer diameter (Diameter)"
            )

        ignored = {
            VtSmplGeom.VT_CYL: ("Width",),
            VtSmplGeom.VT_SPHERE: ("Height", "Width", "AnglSmplHor", "AnglSmplVert"),
        }.get(self.eGeom, ())
        set_but_ignored = [name for name in ignored if getattr(self, name) != 0.0]
        if set_but_ignored:
            raise ValueError(
                f"{', '.join(set_but_ignored)} would be ignored for a {self.eGeom.name} "
                "sample; set them to 0 or choose the shape they belong to"
            )
        return self


#: VITESS's own default sample: FILES/sample_files/sampleelastizotr_default.iso,
#: the file the VITESS GUI loads for this module, given as flags. The file
#: holds full scattering ranges (2 and 2 degrees) that the module halves
#: (c:562-563); the flags take half-ranges, hence 1.0 and 1.0. The Default
#: setup records exactly this; it is not the schema default because the C
#: initialisers above are the schema defaults.
SHIPPED_DEFAULT: dict[str, Any] = {
    "pSmplFileName": "sampleelastizotr_default.iso",
    "Repetition": 1,
    "iColor": -1,
    "eGeom": VtSmplGeom.VT_CUBE,
    "ScatMainHor": 0.0,
    "ScatMainVert": 0.0,
    "ScatRangeHor": 1.0,
    "ScatRangeVert": 1.0,
    "AbsorptionC": 0.197,
    "ScatteringC": 0.368,
    "PosSampleX": 50.0,
    "PosSampleY": 0.0,
    "PosSampleZ": 0.0,
    "Diameter": 3.0,
    "Height": 3.0,
    "Width": 3.0,
    "AnglSmplHor": 0.0,
    "AnglSmplVert": 0.0,
    "TranslOutX": 50.0,
    "TranslOutY": 0.0,
    "TranslOutZ": 0.0,
    "AnglOutHor": 0.0,
    "AnglOutVert": 0.0,
}
