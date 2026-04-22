"""
Growth curve plotting utilities for robotic adaptive laboratory evolution (ALE).

This module provides functions for visualizing optical density (OD) measurements
from high-throughput robotic ALE experiments. It supports plotting growth curves
for experimental replicates and contamination monitoring data.
"""

import pandas as pd
import numpy as np
import matplotlib.pyplot as plt
from matplotlib import colormaps
from matplotlib.lines import Line2D
from matplotlib.ticker import LogFormatter, LogLocator


def plot_OD_replicates(df, subtract_background=False, blank=False,
                       yscale='log', append_title='', pdf=None, png=False, png_path=None):
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
        - 'Microtiter plate well': Well position (e.g., 'A1', 'B2')
        - 'datetime': Timestamp of measurement
        - 'od': Optical density reading
        - 'background': Background OD reading (for subtraction)
        - 'transfer': Transfer number (integer)
        - 'Plotting group': Group identifier for plot organization
        - 'Plotting group name': Human-readable group name
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
    if len(df.groupby(['Plotting group', 'Plotting group name'])) > 1:
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

    # ===== SAMPLE DEFINITION AND STYLING =====
    if blank:
        # For blank data: samples are unique wells, labeled by well name
        samples = (df[['Microtiter plate well']]
                   .drop_duplicates()
                   .dropna()
                   .sort_values('Microtiter plate well'))
        samples['label'] = samples['Microtiter plate well']
        # Use extended tab20 colormap for blank wells
        colors = colormaps['tab20'].colors * 3
        samples['color'] = colors[:len(samples)]
    else:
        # For experimental data: samples are Name + well combinations
        samples = (df[['Name', 'Microtiter plate well']]
                   .drop_duplicates()
                   .dropna()
                   .sort_values('Name'))
        samples['label'] = (samples['Name'] + " (" +
                             samples['Microtiter plate well'] + ")")
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
                    (df['Microtiter plate well'] == sample['Microtiter plate well']) &
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
                    sample_data['datetime'],
                    sample_data[value_column],
                    color=sample['color'],
                    marker='o',
                )
            else:
                # Experimental data plotted as lines
                plt.plot(
                    sample_data['datetime'],
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
    plt.xticks(all_datetimes[tick_indices], all_datetimes[tick_indices],
               rotation=45, ha='right')

    # Secondary x-axis showing transfer numbers
    df['datetime'] = pd.to_datetime(df['datetime'])
    transfer_datetimes = df.groupby('transfer')['datetime'].agg("median")
    secax = ax.secondary_xaxis('top')
    secax.set_xticks(transfer_datetimes, df['transfer'].sort_values().unique())
    secax.set_xlabel('transfer')

    # ===== FINALIZE PLOT =====
    plt.title(append_title, fontsize=20, y=1.15)
    plt.legend(handles=legend_handles, labels=[h.get_label() for h in legend_handles],
               loc='upper center')

    if pdf:
        plt.savefig(pdf, format='pdf', bbox_inches='tight')

    if png:
        plt.savefig(png_path, format='png', bbox_inches='tight', dpi=300)

    plt.show()


def plot_OD_contam(df, subtract_background=False, yscale='log',
                   append_title='', pdf=None, png=False, png_path=None):
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
    if len(df.groupby('reading')) > 1 or df['reading'].unique()[0] != 'contam':
        raise ValueError("This function is designed for 'contam' readings only.")

    if png and png_path is None:
        raise ValueError("png_path must be provided when png=True")

    # ===== DATA PREPARATION =====
    df = df.sort_values('datetime')
    df['od_background_subtracted'] = df['od'] - df['background']
    value_column = 'od_background_subtracted' if subtract_background else 'od'

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
        df['datetime'],
        df[value_column],
        marker='o',
    )

    # Annotate outlier wells
    for i, label in enumerate(outlier_labels):
        if label == '':
            continue
        plt.annotate(
            label,
            (df['datetime'].iloc[i], df[value_column].iloc[i]),
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

    # X-axis setup
    plt.xticks(rotation=45)

    # Add reference line at mean OD
    plt.axhline(y=contam_mean, color='r', linestyle='--', label='Mean OD')

    # Secondary x-axis showing transfer numbers
    df['datetime'] = pd.to_datetime(df['datetime'])
    transfer_starts = df.groupby('transfer')['datetime'].agg(
        lambda x: sorted(list(set(x)))[0])
    secax = ax.secondary_xaxis('top')
    secax.set_xticks(transfer_starts, np.arange(1, df['transfer'].max() + 1, 1))
    secax.set_xlabel('transfer')

    # ===== FINALIZE PLOT =====
    plt.title(append_title + " ", fontsize=20)
    plt.legend()

    if pdf:
        plt.savefig(pdf, format='pdf', bbox_inches='tight')

    if png:
        plt.savefig(png_path, format='png', bbox_inches='tight', dpi=300)

    plt.show()
