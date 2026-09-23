# Test fixtures

## The monitor files

Written by VITESS 3.8's own `monitor1D` and `monitor2D` binaries, compiled from
`iffgit.fz-juelich.de/vitess/vitess.git@6bd0e0066c4667444368dd2492f77821ff8a5609`
by this repository's `Dockerfile`. They are not hand-written, and that is the point: the
first-generation reader was written against a remembered format and got every
layout wrong, and a fixture written to match a reader can never show that.

| File | `Monitor2DParameters.format` | Layout |
|---|---|---|
| `monitor1D.dat` | — | four columns: bin centre, intensity, error, trajectories |
| `monitor2D-F0.dat` | `matrix` (**the schema default**) | x bin centres, then one row per y bin |
| `monitor2D-F1.dat` | `xyz` | one row per cell, five columns |
| `monitor2D-F2.dat` | `matrix_compact` | as `matrix`, fewer digits |
| `monitor2D-F3.dat` | `xyz_compact` | as `xyz`, fewer digits |
| `monitor2D-F4.dat` | `matrix_integer` | as `matrix`, but **counts** over the measurement time, not a rate |

All five 2D files are the same measurement written five ways, which is what
`test_every_2d_rate_layout_reads_back_the_same_measurement` uses: four files
that disagree would mean the reader has one of the layouts wrong.

## How they were produced

Inputs are VITESS's own module test (`tests/module_tests/Monitors/` in the
VITESS source tree), with the bin counts reduced so the files stay small --
22 bins for 1D and 12 x 12 for 2D, instead of 110 and 100 x 100.

```sh
V=/vitess/MODULES; S=_Linux_$(uname -m); P=/tmp/run; L=$P/log-
cp SrcConst.mod constant.dat $P/        # from VITESS tests/module_tests/Monitors
cd $P
export GSL_RNG_SEED=1 GSL_RNG_TYPE=ran3

SRC="$V/source$S -S1 --Z1 --U1.0e-25 --G1 --T0 --B10000 --P$P --N1 --L${L}01 \
    -a$P/SrcConst.mod -n1e4 -l1 -m1 -M10 -d1 -b0.0 -c0.0 -y0.5 -z0.5 -D200 \
    -w2 -h2 -i0 -s200 -X1 -Y1 -V1 -P100 -A0 -k0"

$SRC | $V/monitor1D$S --Z1 --U1.0e-25 --G1 --T0 --B10000 --P$P --N2 --L${L}02 \
    -O$P/monitor1D.dat -X5 -w0 -W11 -x22 -p1 -e0 --Fno_file

for fmt in 0 1 2 3 4; do
  $SRC | $V/monitor2D$S --Z1 --U1.0e-25 --G1 --T0 --B10000 --P$P --N2 --L${L}02 \
      -O$P/monitor2D-F$fmt.dat -X1 -Y2 -w-3 -h-3 -W3 -H3 -x12 -y12 -p1 -e0 \
      -F$fmt --Fno_file
done
```

The source is a 2 cm x 2 cm constant-wavelength beam, which is why the 2D
fixtures hold a square spot centred on the axis and the 1D fixture holds signal
between 1.25 and 9.75 A. Both properties are asserted in
`tests/test_monitor_plots.py`.

Two things worth knowing if these are ever regenerated:

- `constant.dat` must be copied into the project directory. The source module
  reads its wavelength distribution from there and exits 255 without it.
- `--Fno_file` marks the **last** module of a pipeline. On any earlier module it
  stops trajectories reaching the next one, which looks like a simulation that
  ran and monitored nothing.

## The capture_flux logs

`capture_flux-default.log` and `capture_flux-rectangular.log` are what a run's
`result.txt` holds: every module's log, concatenated in order the way
`postprocess_logs` does it. Written by VITESS 3.8's own `source` and
`capture_flux` binaries, from the same revision and the same source settings as
the monitor files above. capture_flux has no output file; these three log lines
are its whole result, and `read_capture_flux` is tested against them:

```
Reference wavelength:        1.798 A
Captured intensity  :    5.991e+10 +/-    9.676e+08 n/s       by       4401 trajectories
Capture flux        :    1.664e+09 +/-    2.688e+07 n/(s*cm^2)
```

The capture_flux arguments are exactly what `CaptureFluxParameters` produces:
the defaults (no foil) for one, and a 6 cm x 6 cm foil with a 1-5 A wavelength
window for the other.

```sh
V=/vitess/MODULES; S=_Linux_$(uname -m); P=/tmp/cf
cp SrcConst.mod constant.dat $P/        # from VITESS tests/module_tests/Monitors
cd $P
export GSL_RNG_SEED=1 GSL_RNG_TYPE=ran3

SRC="$V/source$S -S1 --Z1 --U1.0e-25 --G1 --T0 --B10000 --P$P --N1 \
    -a$P/SrcConst.mod -n1e4 -l1 -m1 -M10 -d1 -b0.0 -c0.0 -y0.5 -z0.5 -D200 \
    -w2 -h2 -i0 -s200 -X1 -Y1 -V1 -P100 -A0 -k0"

run() { name=$1; shift; L=$P/log-$name-
  $SRC --L${L}01 | $V/capture_flux$S --Z1 --U1.0e-25 --G1 --T0 --B10000 --P$P \
      --N2 --L${L}02 "$@" --Fno_file
  cat ${L}?? > $P/capture_flux-$name.log; rm ${L}??; }

run default -R1.798 -t0 -r0.0 -y0.0 -z0.0 -w0.0 -W0.0 -h0.0 -H0.0 -l0.0 -L0.0
run rectangular -R1.798 -t2 -r0.0 -y0.0 -z0.0 -w-3.0 -W3.0 -h-3.0 -H3.0 -l1.0 -L5.0
```

With no foil the capture flux equals the captured intensity, because
capture_flux divides by an assumed 1 cm^2; `test_capture_flux.py` asserts it.

## The flatness monitor files

`monitor1D-flatness-*.dat` are horizontal-position profiles (`-X1`, `pos_y`)
written by VITESS 3.8's own `source` and `monitor1D`, from the same revision and
the same constant source as the files above, and read by
`test_profile_flatness.py`. The source is a uniformly bright 3 cm x 3 cm
moderator seen through a propagation window 200 cm away, so the beam is flat
across the window; the window width (`-w`) and the trajectory count (`-n`) are
what differ:

| File | Window | Trajectories | Bins | Verdict |
|---|---|---|---|---|
| `monitor1D-flatness-pass.dat` | 2 cm | 10^6 | 40 | pass |
| `monitor1D-flatness-half-edges.dat` | 0.9 cm | 10^6 | 40 | fail: the two edge bins are half filled |
| `monitor1D-flatness-empty-edges.dat` | 0.6 cm | 10^6 | 40 | fail: four empty bins |
| `monitor1D-flatness-inconclusive.dat` | 2 cm | 10^4 | 40 | inconclusive: the same flat beam, too few trajectories to decide |
| `monitor1D-flatness-100-bins.dat` | 2 cm | 10^4 | 100 | not judged: 0.04 cm bins |

Produced in the MCP container with `./vitess mcp-exec sh < script.sh`, after
copying `SrcConst.mod` and `constant.dat` into `/tmp/flat`:

```sh
V=/vitess/MODULES; S=_Linux_$(uname -m); P=/tmp/flat
cd $P
export GSL_RNG_SEED=1 GSL_RNG_TYPE=ran3

# $1 output name, $2 trajectories, $3 window width [cm], $4 bins
run() {
  $V/source$S -S1 --Z1 --U1.0e-25 --G1 --T0 --B10000 --P$P --N1 --L$P/log-$1-01 \
      -a$P/SrcConst.mod -n$2 -l1 -m1 -M10 -d1 -b0.0 -c0.0 -y0.5 -z0.5 -D200 \
      -w$3 -h2 -i0 -s200 -X1 -Y1 -V1 -P100 -A0 -k0 \
  | $V/monitor1D$S --Z1 --U1.0e-25 --G1 --T0 --B10000 --P$P --N2 --L$P/log-$1-02 \
      -O$P/$1.dat -X1 -w-2.0 -W2.0 -x$4 -p1 -e0 --Fno_file
}

run flatness-pass          1e6 2   40
run flatness-half-edges    1e6 0.9 40
run flatness-empty-edges   1e6 0.6 40
run flatness-inconclusive  1e4 2   40
run flatness-100-bins      1e4 2   100
```

The 100-bin file is also the reason the bin width is part of the criterion: the
beam in it is exactly as flat as in the others, and its worst 0.04 cm bin is
still 15.6 % from the mean, by noise alone.
