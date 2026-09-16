# Test fixtures

## The monitor files

Written by VITESS 3.8's own `monitor1D` and `monitor2D` binaries, compiled from
`iffgit.fz-juelich.de/vitess/vitess.git@develop` by this repository's
`Dockerfile`. They are not hand-written, and that is the point: the
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
V=/vitess/MODULES; S=_Linux_aarch64; P=/tmp/run; L=$P/log-
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
