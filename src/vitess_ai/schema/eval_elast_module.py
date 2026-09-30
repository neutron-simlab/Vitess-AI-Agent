from typing import Annotated, Optional
from pydantic import Field, model_validator
from vitess_ai.schema.base import VitessParameterModel, VtAxis, VtEvalPar

#: eval_elast.c:37. The bin edges live in arrays of BINS + 1 entries.
MAX_BINS = 10000


def logarithmic_bin_count(minimum: float, maximum: float, percent: float) -> int:
    """How many bins eval_elast makes for logarithmic binning, counted as it does.

    InitArrays (c:464-472) starts at `minimum` and multiplies by
    1 + percent/100 until an edge reaches `maximum`. Counting the same way here,
    in the same double precision, gives the same number. The count stops just
    past MAX_BINS, because only whether it fits matters.
    """
    edge, bins = minimum, 0
    while edge < maximum and bins <= MAX_BINS:
        edge *= 1.0 + percent / 100.0
        bins += 1
    return bins


class EvalElastParameters(VitessParameterModel):
    """Configuration model for the eval_elast module (eval_elast.c).

    A 1D spectrum of elastic scattering: the intensity binned by d-spacing,
    momentum transfer Q, scattering angle or wavelength difference. The
    scattering angle is taken from each neutron's direction, measured from the
    x axis of the frame the module before hands on. The wavelength is either
    the reference wavelength (a continuous source) or the one its flight time
    gives (TOF).

    Field names are the C globals. The optional peak integration (-O intensity
    file, -I info file) is not part of this schema: its info file would be an
    upload, and the current sample has no peaks to integrate.

    The defaults are the VITESS GUI's (yaml/3.8/modules/eval_elast.yaml), not
    the C initialisers, which do not run: evaluation parameter 0 and 0 bins count
    nothing. There is no shipped default file for this module. One GUI value is
    changed, the evaluation parameter; its field says why.

    Measured on the app's default pipeline with its 100 000-trajectory beam:
    every neutron is binned, in 12 of the 100 bins from the guide exit (up to
    1.15 deg, the beam's divergence) and in 15 after VITESS's default sample (up
    to 1.45 deg, the corner of its +-1 x +-1 deg band).

    Line references are to eval_elast.c at VITESS 6bd0e006. Every rule below was
    measured on that binary with VITESS's own module tests EvalElast-1_Theta
    (angle, no TOF, 1086 trajectories binned) and EvalElast-2_Q (Q with TOF,
    1444). Their commands reproduce VITESS's reference outputs in every data
    row; only the header's total trajectory count differs (0 in this build).
    """

    eKind: Annotated[VtEvalPar, Field(
        default=VtEvalPar.VT_EVAL_ANGLE,
        description=("-k [-] What the intensity is binned by: VT_EVAL_DSP (1, d-spacing "
                    "in Å), VT_EVAL_Q (2, momentum transfer in 1/Å), VT_EVAL_ANGLE (3, "
                    "scattering angle in deg) or VT_EVAL_LMBD (4, wavelength difference in "
                    "Å). The VITESS GUI suggests d-spacing; the scattering angle is used "
                    "here because it needs no wavelength: at the GUI's 2 Å, VITESS's "
                    "default sample (+-1 deg) is at d above 82 Å, outside any d range."),
        json_schema_extra={"flag": "-k"}
    )]

    EvalFileName: Annotated[str, Field(
        default="eval_elast.dat",
        min_length=1,
        description=("-o [-] Name of the file the spectrum is written to. Without it the "
                    "module writes no spectrum and still exits 0."),
        json_schema_extra={"flag": "-o"}
    )]

    nBins: Annotated[int, Field(
        default=100,
        ge=1,
        le=MAX_BINS,
        description=("-n [-] Number of bins between MinX and MaxX, 1 to 10000. Not used "
                    "with logarithmic binning (LogProz), which makes its own."),
        json_schema_extra={"flag": "-n"}
    )]

    MinX: Annotated[float, Field(
        default=0.0,
        description=("-m [Å, 1/Å or deg] Lower bound of the evaluated range, in the unit of "
                    "eKind: Å for d-spacing and wavelength difference, 1/Å for Q, deg for "
                    "the scattering angle."),
        json_schema_extra={"flag": "-m"}
    )]

    MaxX: Annotated[float, Field(
        default=10.0,
        description="-M [Å, 1/Å or deg] Upper bound of the evaluated range; greater than MinX.",
        json_schema_extra={"flag": "-M"}
    )]

    LogProz: Annotated[float, Field(
        default=0.0,
        ge=0,
        description=("-R [%] Logarithmic binning: each bin's upper edge is this many percent "
                    "above its lower edge. 0 means linear binning into nBins bins."),
        json_schema_extra={"flag": "-R"}
    )]

    DeadSpot: Annotated[float, Field(
        default=0.0,
        ge=0,
        description=("-d [deg] Neutrons scattered by less than this angle are left out, e.g. "
                    "the direct beam in SANS when no beamstop is used. 0 leaves none out."),
        json_schema_extra={"flag": "-d"}
    )]

    LmbdRef: Annotated[float, Field(
        default=2.0,
        ge=0,
        description=("-r [Å] Reference wavelength, the one a velocity selector or "
                    "monochromator sets. Without TOF it is the wavelength of every neutron "
                    "for d-spacing, Q and wavelength difference. Not used for the "
                    "scattering angle, and not used with TOF."),
        json_schema_extra={"flag": "-r"}
    )]

    bProbactiv: Annotated[bool, Field(
        default=True,
        description=("-p [-] Weight each neutron by its probability (yes), or count "
                    "trajectories with weight 1 (no)."),
        json_schema_extra={"flag": "-p"}
    )]

    bExclCount: Annotated[bool, Field(
        default=False,
        description=("-c [-] Exclusive counts: pass on only the neutrons that were binned "
                    "(yes), or every neutron (no). With no, nothing after this module is "
                    "affected by it."),
        json_schema_extra={"flag": "-c"}
    )]

    bTOF: Annotated[bool, Field(
        default=False,
        description=("-w [-] Time of flight: take each neutron's wavelength from its flight "
                    "time over TotLength (yes, TOF instruments), or use LmbdRef for all "
                    "(no, continuous sources)."),
        json_schema_extra={"flag": "-w"}
    )]

    bPathCor: Annotated[bool, Field(
        default=True,
        description=("-t [-] With TOF only: correct the flight path by the neutron's real "
                    "distance from the frame origin (the sample centre) minus DetDist. "
                    "Without TOF it changes nothing."),
        json_schema_extra={"flag": "-t"}
    )]

    eScatAxis: Annotated[VtAxis, Field(
        default=VtAxis.NO_AXIS,
        description=("-A [-] NO_AXIS (-1) for a sample that scatters in every direction; "
                    "Y_AXIS (1) or Z_AXIS (2) for one that scatters only horizontally or "
                    "only vertically, e.g. a liquid surface (Z_AXIS)."),
        json_schema_extra={"flag": "-A"}
    )]

    TotLength: Annotated[Optional[float], Field(
        default=None,
        gt=0,
        description=("-l [cm] With TOF only, and then required: the nominal flight path "
                    "from where t = 0 is set (source or pulse chopper) to the detector."),
        json_schema_extra={"flag": "-l"}
    )]

    DetDist: Annotated[Optional[float], Field(
        default=None,
        gt=0,
        description=("-D [cm] With TOF and path correction only, and then required: the "
                    "nominal distance from the sample to the detector."),
        json_schema_extra={"flag": "-D"}
    )]

    TimeOffset: Annotated[float, Field(
        default=0.0,
        description=("-T [ms] Shift of every neutron's time, t -> t - TimeOffset, before the "
                    "TOF wavelength and the time window are worked out; e.g. half a long "
                    "pulse."),
        json_schema_extra={"flag": "-T"}
    )]

    EvalTimeMin: Annotated[Optional[float], Field(
        default=None,
        description=("-e [ms] Only neutrons arriving at or after this time are binned. "
                    "Omitted: no lower limit."),
        json_schema_extra={"flag": "-e"}
    )]

    EvalTimeMax: Annotated[Optional[float], Field(
        default=None,
        description=("-E [ms] Only neutrons arriving at or before this time are binned. "
                    "Omitted: no upper limit."),
        json_schema_extra={"flag": "-E"}
    )]

    nColour: Annotated[int, Field(
        default=-1,
        ge=-1,
        description="-C [-] Only neutrons of this colour are binned; -1 bins every neutron.",
        json_schema_extra={"flag": "-C"}
    )]

    @model_validator(mode="after")
    def the_spectrum_counts_something(self) -> "EvalElastParameters":
        """Refuse a spectrum that VITESS runs and leaves empty, or stops on.

        Measured with test 1 (1086 trajectories binned):

        ===========================  =======================================
        -k0 (the C default)          0 binned, exit 0 -- no case matches
        -m90 -M90, -m180 -M0         0 binned, exit 0
        -n0                          0 binned, exit 0 (refused by the field)
        -n10001                      exit 99, "number of bins must be <= 10000"
        -A0 (x axis), -A3            exit 255, "Invalid scattering axis"
        -e5 -E1                      0 binned, exit 0
        -C-2                         0 binned (refused by the field)
        ===========================  =======================================
        """
        if self.eKind == VtEvalPar.VT_NO_EVAL:
            raise ValueError(
                "eKind must name what to bin by: VT_EVAL_DSP (1), VT_EVAL_Q (2), "
                "VT_EVAL_ANGLE (3) or VT_EVAL_LMBD (4); VT_NO_EVAL counts nothing"
            )
        if self.MinX >= self.MaxX:
            raise ValueError("MinX must be smaller than MaxX; otherwise nothing is binned")
        if self.eScatAxis == VtAxis.X_AXIS:
            raise ValueError(
                "eScatAxis must be NO_AXIS (-1), Y_AXIS (1) or Z_AXIS (2); X_AXIS stops "
                "the module"
            )
        if (
            self.EvalTimeMin is not None
            and self.EvalTimeMax is not None
            and self.EvalTimeMin >= self.EvalTimeMax
        ):
            raise ValueError(
                "EvalTimeMin must be smaller than EvalTimeMax; otherwise nothing is binned"
            )
        return self

    @model_validator(mode="after")
    def logarithmic_bins_fit(self) -> "EvalElastParameters":
        """Logarithmic binning makes its own bins, and the C code does not check them.

        Measured with test 1 (MaxX 180):

        ===============================  =====================================
        -R5 -m0                          exit 255, "lower bound value must not
                                         be zero for logarithmic binning"
        -R-5 -m1                         exit 139, a crash (refused by the field)
        -R0.001 -m0.001 (1.2e6 bins)     exit 139, a crash
        -R0.05 -m1 (10 387 bins)         exit 0, but it writes past the 10 001
                                         entries of its bin arrays (c:76-84)
        -R5 -m1 -n7                      identical to -R5 -m1: nBins is ignored
        ===============================  =====================================
        """
        if self.LogProz == 0:
            return self
        if self.MinX <= 0:
            raise ValueError(
                "logarithmic binning (LogProz) needs MinX greater than 0; each edge is "
                "the one before times a factor, so it never leaves 0"
            )
        bins = logarithmic_bin_count(self.MinX, self.MaxX, self.LogProz)
        if bins > MAX_BINS:
            raise ValueError(
                f"logarithmic binning from {self.MinX:g} to {self.MaxX:g} in {self.LogProz:g}% "
                f"steps makes more than {MAX_BINS} bins, more than eval_elast can hold; "
                "raise LogProz or MinX"
            )
        if self.nBins != type(self).model_fields["nBins"].default:
            raise ValueError(
                "nBins would be ignored with logarithmic binning (LogProz), which makes "
                "its own bins; leave nBins at its default or set LogProz to 0"
            )
        return self

    @model_validator(mode="after")
    def the_wavelength_is_known(self) -> "EvalElastParameters":
        """Each neutron's wavelength comes from the reference or from its flight time.

        c:188 sets the flight path to TotLength + (distance from the origin) -
        DetDist with path correction, TotLength without; c:197 takes the
        wavelength from it with TOF, and LmbdRef without. Measured:

        ===================================  ===================================
        no TOF, -r0, Q                       0 binned: Q is infinite
        no TOF, -r0, d-spacing               all 1086 in the first bin: d = 0
        no TOF, -r0, wavelength difference   binned as 0 minus the true wavelength
        no TOF, -r0, angle                   identical to -r1.5: not used
        TOF without -l                       1443 of 1444 binned, spectrum changed
        -l0, -l-5                            exit 255, "you must define a flight
                                             path > 0.0"
        TOF, path correction, no -D          same count, spectrum shifted
        TOF, no path correction, no -D       identical to with -D100: not used
        no TOF, with -l2101 -D100            identical to without: not used
        TOF, -r5                             identical to without: not used
        ===================================  ===================================

        A value the user gave and would not get is refused; a value left at its
        default was not asked for, so it passes.
        """
        needs_wavelength = self.eKind in (
            VtEvalPar.VT_EVAL_DSP, VtEvalPar.VT_EVAL_Q, VtEvalPar.VT_EVAL_LMBD
        )
        if not self.bTOF:
            if needs_wavelength and self.LmbdRef <= 0:
                raise ValueError(
                    f"{self.eKind.name} without TOF needs LmbdRef greater than 0: it is "
                    "the wavelength of every neutron"
                )
            ignored = [name for name in ("TotLength", "DetDist") if getattr(self, name) is not None]
            if ignored:
                raise ValueError(
                    f"{', '.join(ignored)} would be ignored without TOF (bTOF); leave "
                    "them out or switch TOF on"
                )
            return self

        if self.TotLength is None:
            raise ValueError(
                "TOF (bTOF) needs TotLength, the flight path from t = 0 to the detector; "
                "without it the wavelengths are wrong"
            )
        if self.bPathCor and self.DetDist is None:
            raise ValueError(
                "TOF with path correction (bPathCor) needs DetDist, the nominal "
                "sample-detector distance; without it every flight path is too long by "
                "the real distance"
            )
        if not self.bPathCor and self.DetDist is not None:
            raise ValueError(
                "DetDist would be ignored without path correction (bPathCor); leave it "
                "out or switch path correction on"
            )
        if self.LmbdRef not in (0.0, type(self).model_fields["LmbdRef"].default):
            raise ValueError(
                "LmbdRef would be ignored with TOF (bTOF), which takes each wavelength "
                "from the flight time; set it to 0 or switch TOF off"
            )
        return self
