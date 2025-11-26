# -*- coding: utf-8 -*-

import sys
import numpy as np
import matplotlib.pyplot as plt

def plot2D(counts, xaxis, yaxis, by, bz, fname, cmap="viridis"):
    """
    Plots a 2D heatmap of `counts` with axes labeled.

    Parameters:
    - counts (2D array-like): Data to be visualized as an image.
    - xaxis (str): Label for the x-axis.
    - yaxis (str): Label for the y-axis.
    - by (array-like): Bin edges or midpoints for the x-axis.
    - bz (array-like): Bin edges or midpoints for the y-axis.
    - fname (str): File name or descriptor; can influence saving behavior.
    - cmap (str, optional): Colormap for the image. Default is "viridis".
    """
    
    plt.figure()
    plt.imshow(counts, origin="lower", extent=[np.min(by), np.max(by), np.min(bz), np.max(bz)], cmap=cmap, aspect='auto')
    plt.xlabel(xaxis)
    plt.ylabel(yaxis)
    plt.title(fname)
    plt.colorbar(label="Counts")
    plt.tight_layout()
    plt.show()

def plot1D(x, counts, error, xaxis, yaxis, fname):
    """
    Plots a 1D histogram with error bars.

    Parameters:
    - x (array-like): Bin centers for the histogram.
    - counts (array-like): Heights of the histogram bars.
    - error (array-like): Uncertainty values for each bin.
    - xaxis (str): Label for the x-axis.
    - yaxis (str): Label for the y-axis.
    - fname (str): File name or descriptor; can influence log scaling.
    """
    
    if len(x) == 0 or len(counts) == 0 or len(error) == 0:
        raise ValueError("Input arrays must not be empty.")
    
    if (any(error<0)):
        print("Check your data because some error values are below zero!")
        error = np.abs(error)
    
    plt.figure()
    plt.bar(x, counts, width=x[1]-x[0], color="black", alpha=0.3)
    plt.errorbar(x, counts, yerr=error, ls="dotted", marker=None, capsize=2,alpha=0.2)
    plt.xlabel(xaxis.capitalize())
    plt.ylabel(yaxis.capitalize())
    plt.title(fname)
    plt.grid()
    plt.tight_layout()
    plt.show()

def get_info(line):
    parts = line.split(":")
    nbin = parts[1].strip().split(" ")[0]
    axis = parts[2]
    return float(nbin), axis

def get_value(line, key):
    try:
        i = line.index(key)
        i = line.index(":", i) + 1
        try:
            j = line.index("#", i)
        except ValueError:
            j = len(line)
        return line[i:j].strip()
    except ValueError:
        return None

def read_mfile(fn):
    """
    Reads data from a 2D monitor file and extracts relevant information.

    Parameters:
    - fn (str): File path of the monitor file to be read.

    Returns:
    - nbiny (int): Number of bins in the y axis.
    - nbinz (int): Number of bins in the z axis.
    - by (numpy.ndarray): Array of bin values for the y axis.
    - bz (numpy.ndarray): Array of bin values for the z axis.
    - counts (numpy.ndarray): 2D array of counts for each bin.
    - xaxis (str): Label for the x axis.
    - yaxis (str): Label for the y axis.

    If an error occurs during file reading or if the file format is invalid,
    the function returns zeros for all output parameters.
    """
    try:
        fin = open(fn, "r")
        print("read correctly")
    except:
        print("Could not open file.")
        return 0

    header_lines = []
    content_lines = []
    for line in fin.readlines():
        if line.startswith("#"):
            header_lines.append(line.rstrip())
        elif line.rstrip():
            content_lines.append(line.rstrip())

    hline = header_lines[0]
    if "2D" in hline:
        ftype = "mon2D"
    elif "1D" in hline:
        ftype = "mon1D"
    else:
        print("Wrong type of file!")
        return 0

    nbiny, nbinz = 0, 0
    xaxis, yaxis = "x", "y"
    title = fn
    # parse
    try:
        # old format
        if hline.startswith("#Monitor 2D Intensity"):
            split1 = hline.split("bins:")
            nbiny = int(split1[0].split(":")[-1])
            xaxis = split1[1].strip().split(" ")[0]
            nbinz = split1[1].strip().split(" ")[-1]
            yaxis = split1[2]
        for line in header_lines:
            if line.startswith("# x-axis"):
                nbiny, xaxis = get_info(line)
                continue
            if line.startswith("# y-axis"):
                nbinz, yaxis = get_info(line)
                continue
        # new format
        for line in header_lines:
            xaxis = get_value(line, 'x_label') or xaxis
            yaxis = get_value(line, 'y_label') or yaxis
            title = get_value(line, 'title') or title
            if 'x_range' in line:
                x_range = get_value(line, 'x_range')
                x_range = [float(x) for x in x_range.split(",")]
            if 'y_range' in line:
                y_range = get_value(line, 'y_range') or None
                y_range = [float(y) for y in y_range.split(",")]
    except:
        print("Error parsing file, no labels will be used.")

    bz = []
    counts = []
    if ftype == "mon2D":
        by = np.fromstring(content_lines[1], dtype=float, sep=" ")
    for line in content_lines[2:]:
        z = np.fromstring(line, dtype=float, sep=" ")
        bz.append(z[0])
        counts.append(z[1:])
    if ftype == "mon2D":
        by = np.array(by)
        bz = np.array(bz)
        plot2D(np.array(counts), xaxis, yaxis, x_range, y_range, title)

    elif ftype == "mon1D":
        counts = np.array(counts)
        plot1D(bz, counts[:,0], counts[:,1], xaxis, r"Intensity [n/s]", title)

if __name__ == "__main__":
    read_mfile(sys.argv[1])
