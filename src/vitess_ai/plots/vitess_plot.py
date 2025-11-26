# -*- coding: utf-8 -*-

import sys
import numpy as np
import matplotlib.pyplot as plt
import plotly.graph_objects as go
from plotly.utils import PlotlyJSONEncoder
import json

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

def plot1d_plotly(x, counts, error, xaxis, yaxis, fname):
    """
    Creates an interactive 1D plot with error bars using Plotly.
    
    Parameters:
    - x (array-like): Bin centers for the histogram.
    - counts (array-like): Heights of the histogram bars.
    - error (array-like): Uncertainty values for each bin.
    - xaxis (str): Label for the x-axis.
    - yaxis (str): Label for the y-axis.
    - fname (str): Title for the plot.
    
    Returns:
    - dict: Plotly figure as JSON-serializable dict
    """
    if len(x) == 0 or len(counts) == 0 or len(error) == 0:
        raise ValueError("Input arrays must not be empty.")
    
    # Ensure error values are non-negative
    error = np.abs(error)
    
    # Convert to numpy arrays if needed
    x = np.array(x)
    counts = np.array(counts)
    error = np.array(error)
    
    # Calculate bar width
    if len(x) > 1:
        bar_width = x[1] - x[0]
    else:
        bar_width = 1.0
    
    # Create figure with subplot
    fig = go.Figure()
    
    # Add bar chart
    fig.add_trace(go.Bar(
        x=x,
        y=counts,
        width=bar_width,
        marker=dict(
            color='rgba(0, 0, 0, 0.3)',
            line=dict(width=0)
        ),
        name='Counts',
        hovertemplate='<b>%{x:.4f}</b><br>Count: %{y:.4f}<extra></extra>',
    ))
    
    # Add error bars as scatter plot with error_y
    fig.add_trace(go.Scatter(
        x=x,
        y=counts,
        mode='markers',
        marker=dict(
            size=4,
            color='rgba(0, 0, 0, 0.8)',
        ),
        error_y=dict(
            type='data',
            array=error,
            visible=True,
            thickness=1.5,
            width=3,
        ),
        name='Error',
        hovertemplate='<b>%{x:.4f}</b><br>Count: %{y:.4f} ± %{error_y.array:.4f}<extra></extra>',
        showlegend=False,
    ))
    
    # Update layout
    fig.update_layout(
        title=dict(
            text=fname,
            x=0.5,
            font=dict(size=16)
        ),
        xaxis=dict(
            title=xaxis.capitalize(),
            showgrid=True,
            gridcolor='rgba(128, 128, 128, 0.2)',
        ),
        yaxis=dict(
            title=yaxis.capitalize(),
            showgrid=True,
            gridcolor='rgba(128, 128, 128, 0.2)',
        ),
        template='plotly_white',
        hovermode='x unified',
        showlegend=False,
        height=500,
        margin=dict(l=60, r=20, t=60, b=60),
    )
    
    return fig


def plot2d_plotly(counts, xaxis, yaxis, by, bz, fname, cmap="Viridis"):
    """
    Creates an interactive 2D heatmap using Plotly.
    
    Parameters:
    - counts (2D array-like): Data to be visualized as a heatmap.
    - xaxis (str): Label for the x-axis.
    - yaxis (str): Label for the y-axis.
    - by (array-like): Bin edges or midpoints for the x-axis.
    - bz (array-like): Bin edges or midpoints for the y-axis.
    - fname (str): Title for the plot.
    - cmap (str, optional): Colormap name for Plotly. Default is "Viridis".
    
    Returns:
    - dict: Plotly figure as JSON-serializable dict
    """
    # Convert to numpy arrays
    counts = np.array(counts)
    by = np.array(by)
    bz = np.array(bz)
    
    # Create heatmap
    fig = go.Figure(data=go.Heatmap(
        z=counts,
        x=by,
        y=bz,
        colorscale=cmap,
        colorbar=dict(
            title="Counts",
            titleside="right",
        ),
        hovertemplate=f'<b>{xaxis}:</b> %{{x:.4f}}<br>' +
                      f'<b>{yaxis}:</b> %{{y:.4f}}<br>' +
                      '<b>Count:</b> %{z:.4f}<extra></extra>',
    ))
    
    # Update layout
    fig.update_layout(
        title=dict(
            text=fname,
            x=0.5,
            font=dict(size=16)
        ),
        xaxis=dict(
            title=xaxis,
            showgrid=False,
        ),
        yaxis=dict(
            title=yaxis,
            showgrid=False,
            scaleanchor="x",
            scaleratio=1,
        ),
        template='plotly_white',
        height=600,
        margin=dict(l=80, r=20, t=60, b=80),
    )
    
    return fig


def read_mfile_plotly(fn):
    """
    Reads data from a monitor file and returns Plotly figure JSON.
    
    Parameters:
    - fn (str): File path of the monitor file to be read.
    
    Returns:
    - dict: Dictionary with 'success', 'plot_type', 'plot_json', 'title', 'xaxis', 'yaxis'
    """
    try:
        fin = open(fn, "r")
    except Exception as e:
        return {
            "success": False,
            "error": f"Could not open file: {str(e)}",
            "plot_type": None,
            "plot_json": None,
        }
    
    header_lines = []
    content_lines = []
    for line in fin.readlines():
        if line.startswith("#"):
            header_lines.append(line.rstrip())
        elif line.rstrip():
            content_lines.append(line.rstrip())
    
    if not header_lines:
        return {
            "success": False,
            "error": "No header found in file",
            "plot_type": None,
            "plot_json": None,
        }
    
    hline = header_lines[0]
    if "2D" in hline:
        ftype = "mon2D"
    elif "1D" in hline:
        ftype = "mon1D"
    else:
        return {
            "success": False,
            "error": "Wrong type of file!",
            "plot_type": None,
            "plot_json": None,
        }
    
    nbiny, nbinz = 0, 0
    xaxis, yaxis = "x", "y"
    title = fn
    x_range = None
    y_range = None
    
    # Parse header
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
                x_range_str = get_value(line, 'x_range')
                if x_range_str:
                    x_range = [float(x) for x in x_range_str.split(",")]
            if 'y_range' in line:
                y_range_str = get_value(line, 'y_range')
                if y_range_str:
                    y_range = [float(y) for y in y_range_str.split(",")]
    except Exception as e:
        print(f"Error parsing file headers: {e}")
    
    # Parse data
    bz = []
    counts = []
    
    try:
        if ftype == "mon2D":
            if len(content_lines) < 2:
                return {
                    "success": False,
                    "error": "Insufficient data lines for 2D plot",
                    "plot_type": None,
                    "plot_json": None,
                }
            by = np.fromstring(content_lines[1], dtype=float, sep=" ")
            for line in content_lines[2:]:
                z = np.fromstring(line, dtype=float, sep=" ")
                bz.append(z[0])
                counts.append(z[1:])
            
            by = np.array(by)
            bz = np.array(bz)
            counts = np.array(counts)
            
            # Use x_range and y_range if available, otherwise use by and bz
            x_vals = x_range if x_range is not None else by
            y_vals = y_range if y_range is not None else bz
            
            fig = plot2d_plotly(counts, xaxis, yaxis, x_vals, y_vals, title)
            
        elif ftype == "mon1D":
            if len(content_lines) < 1:
                return {
                    "success": False,
                    "error": "Insufficient data lines for 1D plot",
                    "plot_type": None,
                    "plot_json": None,
                }
            for line in content_lines[1:]:
                z = np.fromstring(line, dtype=float, sep=" ")
                bz.append(z[0])
                counts.append(z[1:])
            
            counts = np.array(counts)
            if counts.shape[1] < 2:
                return {
                    "success": False,
                    "error": "1D plot data must have at least 2 columns (counts, error)",
                    "plot_type": None,
                    "plot_json": None,
                }
            
            x_data = np.array(bz)
            counts_data = counts[:, 0]
            error_data = counts[:, 1] if counts.shape[1] > 1 else np.zeros_like(counts_data)
            
            fig = plot1d_plotly(x_data, counts_data, error_data, xaxis, "Intensity [n/s]", title)
        
        # Convert figure to JSON
        plot_json = json.loads(json.dumps(fig.to_dict(), cls=PlotlyJSONEncoder))
        
        return {
            "success": True,
            "plot_type": ftype,
            "plot_json": plot_json,
            "title": title,
            "xaxis": xaxis,
            "yaxis": yaxis,
        }
        
    except Exception as e:
        return {
            "success": False,
            "error": f"Error processing plot data: {str(e)}",
            "plot_type": ftype,
            "plot_json": None,
        }


if __name__ == "__main__":
    read_mfile(sys.argv[1])
