"""
Growth curve plotting utilities for robotic adaptive laboratory evolution (ALE).

This module provides functions for visualizing optical density (OD) measurements
from high-throughput robotic ALE experiments. It supports plotting growth curves
for experimental replicates and contamination monitoring data.
"""

from types import SimpleNamespace

import pandas as pd
import numpy as np
import matplotlib.pyplot as plt
import matplotlib.dates as mdates
from matplotlib import colormaps
from matplotlib.lines import Line2D
from matplotlib.ticker import LogFormatter, LogLocator


# Alternating subtle background colors used to mark robot run phases.
RUN_PHASE_SHADE_COLORS = ['#dbe9f6', '#f6ecdb']


def annotate_run_phases(ax, df, label_y=0.02, xmap=None):
    """Shade the datetime span of each robot run phase behind the curves.

    A dataset can contain multiple run phases per series (each a unique
    ``file_ID``) when the robot stops and restarts. This shades each phase's
    [earliest, latest] ``datetime`` range with an alternating subtle background
    color and labels it ``Run N`` in start-time order. Does nothing when the
    data has a single run phase (or no ``file_ID`` column).

    When ``xmap`` is an active time-axis map (idle-gap compression is in effect,
    from :func:`compress_time_axis`), span bounds and label centers are mapped
    through it so the shading lands on the compressed x coordinates; otherwise
    datetimes are used directly.
    """
    if 'file_ID' not in df.columns:
        return
    spans = df[['file_ID', 'datetime']].copy()
    spans['datetime'] = pd.to_datetime(spans['datetime'])
    spans = spans.dropna(subset=['datetime', 'file_ID'])
    if spans.empty:
        return
    phases = (spans.groupby('file_ID')['datetime']
                   .agg(['min', 'max'])
                   .sort_values('min')
                   .reset_index())
    if len(phases) <= 1:
        return
    m = ((lambda v: xmap.map([v])[0])
         if (xmap is not None and xmap.active) else (lambda v: v))
    for i, row in phases.iterrows():
        color = RUN_PHASE_SHADE_COLORS[i % len(RUN_PHASE_SHADE_COLORS)]
        ax.axvspan(m(row['min']), m(row['max']),
                   facecolor=color, alpha=0.5, zorder=0)
        center = row['min'] + (row['max'] - row['min']) / 2
        ax.text(m(center), label_y, f'Run {i + 1}',
                transform=ax.get_xaxis_transform(),
                ha='center', va='bottom', fontsize=10, color='#555555',
                zorder=3)


def compress_time_axis(datetimes, max_gap_hours=24):
    """Build a datetime->coordinate map that collapses long idle gaps.

    Any gap between consecutive (unique, sorted) timestamps longer than
    ``max_gap_hours`` is shrunk to a small fixed width, so a long robot downtime
    no longer squashes the actual data into a narrow band. In non-collapsed
    segments the map has slope 1, so points within them (transfer medians,
    run-phase span bounds) map faithfully; collapsed segments contain no data by
    definition.

    Returns a lightweight object (``types.SimpleNamespace``) with:
    - ``active`` (bool): False for an identity map (no gap beyond the threshold),
      so callers can render exactly as before in the common case.
    - ``map(values)``: maps datetime-like value(s) to compressed plot
      coordinates (returns an ``ndarray``).
    - ``breaks`` (list): compressed-coord x of each collapsed gap's midpoint.
    """
    t = (pd.to_datetime(pd.Series(datetimes))
         .dropna().drop_duplicates().sort_values())
    xp = mdates.date2num(t.to_numpy())            # strictly increasing knots

    def _make(active, fp, breaks):
        def _map(values):
            x = mdates.date2num(pd.to_datetime(np.asarray(values)))
            return np.interp(x, xp, fp)
        return SimpleNamespace(active=active, map=_map, breaks=breaks)

    if len(xp) < 2:
        return _make(False, xp, [])
    max_gap = max_gap_hours / 24.0                # date2num unit is days
    deltas = np.diff(xp)
    big = deltas > max_gap
    if not big.any():
        return _make(False, xp, [])              # identity: no gap to collapse
    # Collapse each long gap to a small, tight notch sized from the data's own
    # spacing (a broken axis reads best as a narrow break, not a wide band).
    normal = deltas[~big]
    notch = 1.5 * np.median(normal) if normal.size else max_gap
    collapsed = np.where(big, notch, deltas)
    fp = np.concatenate([[xp[0]], xp[0] + np.cumsum(collapsed)])
    breaks = [fp[i] + notch / 2.0                # midpoint of each collapsed gap
              for i in range(len(deltas)) if big[i]]
    return _make(True, fp, breaks)


def draw_axis_breaks(ax, xpositions, d=0.008):
    """Draw diagonal break marks at each cut on the bottom axis spine.

    ``xpositions`` are in data coordinates (compressed). Marks are sized in
    axes fractions so they look consistent regardless of the data range. Call
    after plotting and limits are finalized so the data->axes transform is
    stable.
    """
    for x in xpositions:
        xf = ax.transAxes.inverted().transform(
            ax.transData.transform((x, 0)))[0]
        for offset in (-1.5 * d, 1.5 * d):
            ax.plot([xf + offset - d, xf + offset + d], [-d, d],
                    transform=ax.transAxes, color='k', lw=1,
                    clip_on=False, zorder=5)


def plot_OD_replicates(df, subtract_background=False, blank=False,
                       yscale='log', append_title='', pdf=None, png=False,
                       png_path=None, max_gap_hours=24):
    """
    Plot optical density growth curves for experimental replicates.

    Creates a time-series plot showing OD measurements for different samples
    across multiple transfers. Each sample is plotted with a unique color,
    and replicates are shown together. The plot includes a secondary x-axis
    showing transfer numbers.

    Parameters
    ----------
    df : pandas.DataFrame
        DataFrame containing OD measurements with required columns:
        - 'Name': Sample identifier
        - 'Microtiter_plate_well': Well position (e.g., 'A1', 'B2')
        - 'datetime': Timestamp of measurement
        - 'od': Optical density reading
        - 'background': Background OD reading (for subtraction)
        - 'transfer': Transfer number (integer)
        - 'Plotting_group_number': Group identifier for plot organization
        - 'Plotting_group_name': Human-readable group name
    subtract_background : bool, default False
        If True, subtract background OD readings from all measurements
    blank : bool, default False
        If True, plot blank/control data as scatter points with wells as samples
    yscale : str, default 'log'
        Y-axis scale ('log' or 'linear')
    append_title : str, default ''
        Additional text to append to the plot title
    pdf : str or None, default None
        If provided, save plot to PDF file at this path
    png : bool, default False
        If True, save plot to PNG file (requires png_path to be provided)
    png_path : str or None, default None
        Path to save PNG file when png=True
    max_gap_hours : float, default 24
        Idle gaps on the time axis longer than this many hours (e.g. a robot
        downtime between run phases) are collapsed to a small fixed width and
        marked with diagonal break marks, so the actual data fills the plot.
        Applied automatically only when such a gap exists; otherwise the x-axis
        is unchanged.

    Returns
    -------
    None
        Displays the plot and optionally saves to PDF and/or PNG

    Raises
    ------
    ValueError
        If dataframe contains multiple plotting groups (use separate calls)
    """

    # ===== DATA VALIDATION =====
    if len(df) == 0 :
        raise ValueError("There is no data in the input df.")
    
    if len(df.groupby(['Plotting_group_number', 'Plotting_group_name'])) > 1:
        raise ValueError(
            f"There appear to be multiple plotting groups in dataframe. "
            f"Ensure that you want all these samples in one graph: "
            f"{df['Name'].unique()}"
        )

    if png and png_path is None:
        raise ValueError("png_path must be provided when png=True")

    # ===== DATA PREPARATION =====
    df = df.sort_values(['datetime', 'Name'])
    df['od_background_subtracted'] = df['od'] - df['background']
    value_column = 'od_background_subtracted' if subtract_background else 'od'

    # Map real datetimes -> compressed x coordinates, collapsing long idle gaps.
    # Inactive (identity) unless a gap exceeds max_gap_hours, so the common
    # single-run-phase case renders exactly as before.
    xmap = compress_time_axis(df['datetime'].unique(), max_gap_hours)
    X = (lambda v: xmap.map(v)) if xmap.active else (lambda v: v)

    # ===== SAMPLE DEFINITION AND STYLING =====
    if blank:
        # For blank data: samples are unique wells, labeled by well name
        samples = (df[['Microtiter_plate_well']]
                   .drop_duplicates()
                   .dropna()
                   .sort_values('Microtiter_plate_well'))
        samples['label'] = samples['Microtiter_plate_well']
        # Use extended tab20 colormap for blank wells
        colors = colormaps['tab20'].colors * 3
        samples['color'] = colors[:len(samples)]
    else:
        # For experimental data: samples are Name + well combinations
        samples = (df[['Name', 'Microtiter_plate_well']]
                   .drop_duplicates()
                   .dropna()
                   .sort_values('Name'))
        samples['label'] = (samples['Name'] + " (" +
                             samples['Microtiter_plate_well'] + ")")
        # Use basic colors plus tab20 for experimental samples
        colors = (["blue", "red", "pink", "green", "gray", "brown", "orange", "cyan"] +
                  list(colormaps['tab20'].colors))
        samples['color'] = colors[:len(samples)]

    # ===== FIGURE SETUP =====
    fig, ax = plt.subplots()
    # Scale figure width based on number of transfers for readability
    stretch_factor = 1 + (df['transfer'].max() / 3.4)
    fig_width, fig_height = fig.get_size_inches()
    fig.set_size_inches(fig_width * stretch_factor, fig_height)

    # ===== PLOTTING =====
    legend_handles = []
    for _, sample in samples.iterrows():
        # Create legend handle for this sample
        handle = Line2D([0], [0], label=sample['label'], color=sample['color'])
        legend_handles.append(handle)

        # Plot data for each transfer
        for transfer_num in range(0, int(df['transfer'].max()) + 1):
            if blank:
                # For blank data: filter by well only
                sample_data = df.loc[
                    (df['Microtiter_plate_well'] == sample['Microtiter_plate_well']) &
                    (df['transfer'] == transfer_num)
                ].sort_values('datetime')
            else:
                # For experimental data: filter by Name and well
                sample_data = df.loc[
                    (df['Name'] == sample['Name']) &
                    (df['transfer'] == transfer_num)
                ].sort_values(['Name', 'datetime'])

            if blank:
                # Blank data always plotted as scatter
                plt.scatter(
                    X(sample_data['datetime']),
                    sample_data[value_column],
                    color=sample['color'],
                    marker='o',
                )
            else:
                # Experimental data plotted as lines
                plt.plot(
                    X(sample_data['datetime']),
                    sample_data[value_column],
                    color=sample['color'],
                    marker='o',
                    markersize=4
                )

    # ===== AXIS CONFIGURATION =====
    # Y-axis setup
    ax.set_ylabel('OD', fontsize=20)
    ax.margins(0.01, 0.05)
    ax.set_yscale(yscale)

    # Log scale formatting for y-axis
    ax.yaxis.set_major_locator(LogLocator(base=10.0, numticks=10))
    ax.yaxis.set_minor_locator(LogLocator(base=10.0, subs=range(2, 10)))
    ax.yaxis.set_major_formatter(LogFormatter(minor_thresholds=(2, 0.4)))
    ax.yaxis.set_minor_formatter(LogFormatter(minor_thresholds=(2, 0.4)))
    ax.yaxis.set_ticks_position('both')
    ax.yaxis.set_tick_params(labelright=True, which='both', labelsize=16)
    ax.grid(True, axis='y', linestyle='--', alpha=0.5, which='both')

    # X-axis setup ensuring appropriate tick spacing
    all_datetimes = df['datetime'].unique()
    tick_indices = np.linspace(0, len(all_datetimes) - 1,
                               min(10, len(all_datetimes)), dtype=int)
    tick_datetimes = all_datetimes[tick_indices]
    # When gaps are compressed, x is a synthetic coordinate, so place ticks at
    # the mapped positions and show the real datetimes as formatted labels.
    tick_labels = (pd.to_datetime(tick_datetimes).strftime('%m-%d %H:%M')
                   if xmap.active else tick_datetimes)
    plt.xticks(X(tick_datetimes), tick_labels, rotation=45, ha='right')

    # Secondary x-axis showing transfer numbers
    # df['datetime'] = pd.to_datetime(df['datetime'])
    transfer_datetimes = df.groupby('transfer')['datetime'].agg("median")
    secax = ax.secondary_xaxis('top')
    secax.set_xticks(X(transfer_datetimes),
                     labels=df['transfer'].sort_values().unique())
    secax.set_xlabel('transfer')

    # Indicate robot run-phase time ranges (only drawn when >1 phase present).
    annotate_run_phases(ax, df, xmap=xmap)

    # ===== FINALIZE PLOT =====
    plt.title(append_title, fontsize=20, y=1.15)
    plt.legend(handles=legend_handles, labels=[h.get_label() for h in legend_handles],
               loc='upper center')

    # Mark each collapsed idle gap with diagonal break marks (data->axes
    # conversion needs finalized limits, so draw the canvas first).
    if xmap.active and xmap.breaks:
        fig.canvas.draw()
        draw_axis_breaks(ax, xmap.breaks)

    if pdf:
        plt.savefig(pdf, format='pdf', bbox_inches='tight')

    if png:
        plt.savefig(png_path, format='png', bbox_inches='tight', dpi=300)

    plt.show()


def plot_OD_contam(df, subtract_background=False, yscale='log',
                   append_title='', pdf=None, png=False, png_path=None,
                   max_gap_hours=24):
    """
    Plot contamination monitoring data with outlier detection.

    Creates a scatter plot of OD measurements from contamination readings,
    highlighting wells with abnormally high OD values (>2x mean) as outliers.
    Outlier wells are annotated with their well positions.

    Parameters
    ----------
    df : pandas.DataFrame
        DataFrame containing contamination OD measurements with required columns:
        - 'datetime': Timestamp of measurement
        - 'od': Optical density reading
        - 'background': Background OD reading (for subtraction)
        - 'well': Well position (e.g., 'A1', 'B2')
        - 'transfer': Transfer number (integer)
        - 'reading': Must be 'contam' for all rows
    subtract_background : bool, default False
        If True, subtract background OD readings from all measurements
    yscale : str, default 'log'
        Y-axis scale ('log' or 'linear')
    append_title : str, default ''
        Additional text to append to the plot title
    pdf : str or None, default None
        If provided, save plot to PDF file at this path
    png : bool, default False
        If True, save plot to PNG file (requires png_path to be provided)
    png_path : str or None, default None
        Path to save PNG file when png=True
    max_gap_hours : float, default 24
        Idle gaps on the time axis longer than this many hours (e.g. a robot
        downtime between run phases) are collapsed to a small fixed width and
        marked with diagonal break marks, so the actual data fills the plot.
        Applied automatically only when such a gap exists; otherwise the x-axis
        is unchanged.

    Returns
    -------
    None
        Displays the plot with outlier annotations and optionally saves to PDF and/or PNG

    Raises
    ------
    ValueError
        If dataframe contains readings other than 'contam'
    """
    # ===== DATA VALIDATION =====
    if len(df) == 0 :
        raise ValueError("There is no data in the input contam df.")
    
    if len(df.groupby('reading')) > 1 or df['reading'].unique()[0] != 'contam':
        raise ValueError("This function is designed for 'contam' readings only.")

    if png and png_path is None:
        raise ValueError("png_path must be provided when png=True")

    # ===== DATA PREPARATION =====
    df = df.sort_values('datetime')
    df['od_background_subtracted'] = df['od'] - df['background']
    value_column = 'od_background_subtracted' if subtract_background else 'od'

    # Map real datetimes -> compressed x coordinates, collapsing long idle gaps.
    # Inactive (identity) unless a gap exceeds max_gap_hours.
    xmap = compress_time_axis(df['datetime'].unique(), max_gap_hours)
    X = (lambda v: xmap.map(v)) if xmap.active else (lambda v: v)

    # ===== OUTLIER DETECTION =====
    contam_mean = df['od'].mean()
    df['is_outlier'] = df['od'] > 2 * contam_mean
    outlier_labels = np.where(df['is_outlier'], df['well'], '')

    # ===== FIGURE SETUP =====
    fig, ax = plt.subplots()
    # Scale figure width for contamination plots
    fig_width, fig_height = fig.get_size_inches()
    fig.set_size_inches(fig_width * 3.5, fig_height)

    # ===== PLOTTING =====
    # Plot all contamination readings as scatter points
    plt.scatter(
        X(df['datetime']),
        df[value_column],
        marker='o',
    )

    # Annotate outlier wells
    for i, label in enumerate(outlier_labels):
        if label == '':
            continue
        plt.annotate(
            label,
            (X([df['datetime'].iloc[i]])[0], df[value_column].iloc[i]),
            textcoords="offset points",
            xytext=(10, 0),
            ha='left',
            arrowprops=dict(arrowstyle="->", connectionstyle="arc3,rad=.2"),
            fontsize=12,
            weight='bold'
        )

    # ===== AXIS CONFIGURATION =====
    # Y-axis setup
    ax.set_ylabel('OD', fontsize=20)
    ax.margins(0.01, 0.05)
    ax.set_yscale(yscale)

    # Log scale formatting for y-axis
    ax.yaxis.set_major_locator(LogLocator(base=10.0, numticks=10))
    ax.yaxis.set_minor_locator(LogLocator(base=10.0, subs=range(2, 10)))
    ax.yaxis.set_major_formatter(LogFormatter(minor_thresholds=(2, 0.4)))
    ax.yaxis.set_minor_formatter(LogFormatter(minor_thresholds=(2, 0.4)))
    ax.yaxis.set_ticks_position('both')
    ax.yaxis.set_tick_params(labelright=True, which='both', labelsize=16)
    ax.grid(True, axis='y', linestyle='--', alpha=0.5, which='both')

    # X-axis setup. When gaps are compressed, x is a synthetic coordinate, so
    # place evenly spaced ticks at mapped positions with formatted datetime
    # labels; otherwise keep matplotlib's automatic date ticks.
    if xmap.active:
        all_datetimes = df['datetime'].unique()
        tick_indices = np.linspace(0, len(all_datetimes) - 1,
                                   min(10, len(all_datetimes)), dtype=int)
        tick_datetimes = all_datetimes[tick_indices]
        plt.xticks(X(tick_datetimes),
                   pd.to_datetime(tick_datetimes).strftime('%m-%d %H:%M'),
                   rotation=45, ha='right')
    else:
        plt.xticks(rotation=45)

    # Add reference line at mean OD
    plt.axhline(y=contam_mean, color='r', linestyle='--', label='Mean OD')

    # Secondary x-axis showing transfer numbers
    df['datetime'] = pd.to_datetime(df['datetime'])
    transfer_starts = df.groupby('transfer')['datetime'].agg(
        lambda x: sorted(list(set(x)))[0])
    secax = ax.secondary_xaxis('top')
    secax.set_xticks(X(transfer_starts),
                     np.arange(1, df['transfer'].max() + 1, 1))
    secax.set_xlabel('transfer')

    # Indicate robot run-phase time ranges (only drawn when >1 phase present).
    annotate_run_phases(ax, df, xmap=xmap)

    # ===== FINALIZE PLOT =====
    plt.title(append_title + " ", fontsize=20)
    plt.legend()

    # Mark each collapsed idle gap with diagonal break marks (data->axes
    # conversion needs finalized limits, so draw the canvas first).
    if xmap.active and xmap.breaks:
        fig.canvas.draw()
        draw_axis_breaks(ax, xmap.breaks)

    if pdf:
        plt.savefig(pdf, format='pdf', bbox_inches='tight')

    if png:
        plt.savefig(png_path, format='png', bbox_inches='tight', dpi=300)

    plt.show()
