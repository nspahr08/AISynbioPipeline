#!/usr/bin/env python3
"""Process robotic OD data and upload the results to Google Drive.

Usage:
  process_robotic_od.py <data_dir> <plate_layout> <output_dir> <gdrive_folder_id> [options]

Given a directory of raw robotic plate-reader
.txt files, a plate_layout.csv, an output directory, and a Google Drive
folder ID, it runs the following transformations:

  1. Load and verify the raw OD data files (load_and_verify_robotic_od_data).
  2. Extract the plate-reader files into a tidy dataframe
     (extract_robotic_od_data_to_df).
  3. Resolve the plate layout: load and verify the given file
     (load_and_verify_plate_layout), or, when plate_layout is "-", synthesize
     a one-plotting-group-per-well layout from the data itself
     (build_per_well_layout) so the output is one growth curve per well.
  4. Map the plate layout onto the data (map_plate_layout_to_data).
  5. Compute per-plate background from media-only wells (compute_background).
  6. Correct timestamps from the AccurateTimestamps folder if present
     (correct_timestamps); skipped with a warning when unavailable.
  7. Compute inoculation timestamps and per-reading timepoints
     (compute_inoculation). This step is commented out in the notebook
     because the function was broken; it has since been fixed, so it runs
     by default here. Disable with --skip-inoculation, and use
     --first-reading-is-blank when the first reading of each group is a
     pre-inoculation blank that should be skipped.
  8. Verify and write the processed CSV (verify_and_write_processed_data).
  9. Generate per-plate growth-curve PDFs and per-group PNGs.
 10. Upload the processed CSV, plate PDFs, and PNG plots to Google Drive
     (skip all uploads with --no-upload).

Progress is logged to pipeline.log (alongside the other pipeline scripts)
and to the console.
"""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

import matplotlib
matplotlib.use('Agg')  # Non-interactive backend for headless plot generation.
import matplotlib.pyplot as plt
from matplotlib.backends.backend_pdf import PdfPages

# Add the repo root to the path so the aisynbiopipeline package is importable
# (the workflows package uses absolute aisynbiopipeline.* imports).
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from aisynbiopipeline.workflows.roboticALE import (
    load_and_verify_plate_layout,
    build_per_well_layout,
    load_and_verify_robotic_od_data,
    extract_robotic_od_data_to_df,
    map_plate_layout_to_data,
    compute_background,
    compute_inoculation,
    correct_timestamps,
    verify_and_write_processed_data,
)
from aisynbiopipeline.workflows.growth_curve_plotting import (
    plot_OD_replicates,
    plot_OD_contam,
)


# Default filename pattern for robotic plate-reader files (see notebook).
DEFAULT_FNAME_PATTERN = (
    r'(?P<experiment>\w+)_(?P<timestamp>\d+)_(?P<uniqueID>\w+)_'
    r'(?P<series>\w+)_(?P<transfer>\d+)_(?P<timepoint>\w+).txt'
)
# Subfolder inside the data directory holding accurate-timestamp CSVs.
ATS_SUBFOLDER = 'AccurateTimestamps'
# Sentinel plate_layout value meaning "no layout": synthesize one plotting group
# per well so the output is one growth curve per well per plate.
NO_LAYOUT_SENTINEL = '-'

LOG_FILE = Path(__file__).resolve().parent / 'pipeline.log'


def configure_logging():
    """Set up logging to file and console."""
    LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
    LOG_FILE.touch(exist_ok=True)
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s %(levelname)s %(message)s',
        handlers=[logging.FileHandler(LOG_FILE), logging.StreamHandler()],
    )
    return logging.getLogger(__name__)


def parse_args():
    """Parse command-line arguments."""
    parser = argparse.ArgumentParser(
        description='Process robotic OD data and upload results to Google Drive'
    )
    parser.add_argument('data_dir', help='Directory containing robotic OD .txt data files')
    parser.add_argument(
        'plate_layout',
        help='Path to plate_layout.csv, or "-" to process without a layout '
             '(synthesizes one plotting group per well, giving one growth '
             'curve per well per plate)',
    )
    parser.add_argument('output_dir', help='Directory to write the processed CSV and plots')
    parser.add_argument('gdrive_folder_id', help='Google Drive folder ID to upload results to')
    parser.add_argument(
        '--fname-pattern',
        default=DEFAULT_FNAME_PATTERN,
        help='Regex (with named groups) that data filenames must match',
    )
    parser.add_argument(
        '--experiment',
        default=None,
        help='Experiment name used as the output filename prefix '
             '(default: inferred from the data)',
    )
    parser.add_argument(
        '--ats-folder',
        default=None,
        help=f'Folder with accurate-timestamp CSVs '
             f'(default: <data_dir>/{ATS_SUBFOLDER}; skipped if missing)',
    )
    parser.add_argument(
        '--first-reading-is-blank',
        action='store_true',
        help='Treat the first reading of each group as a pre-inoculation blank '
             'and skip it when computing the inoculation time',
    )
    parser.add_argument(
        '--skip-inoculation',
        action='store_true',
        help='Skip inoculation timestamp / timepoint computation',
    )
    parser.add_argument(
        '--no-upload',
        action='store_true',
        help='Skip all Google Drive uploads (process and write locally only)',
    )
    return parser.parse_args()


def infer_experiment_name(data, override, logger):
    """Determine the experiment prefix used for output filenames."""
    if override:
        return override
    experiments = [e for e in data['experiment'].dropna().unique()]
    if len(experiments) == 1:
        return str(experiments[0])
    logger.warning(
        'Expected a single experiment in the data but found %s; '
        'using "robotic_OD" as the output filename prefix. '
        'Override with --experiment.',
        experiments,
    )
    return 'robotic_OD'


def generate_plate_plots(data, output_dir, plot_dir, experiment, logger):
    """Generate per-plate growth-curve PDFs (and per-group PNGs).

    Returns a list of the plate PDF paths that were written.
    """
    pdf_paths = []
    for plate_name, plate_group in data.groupby('Plate_name'):
        logger.info('Plotting plate %s', plate_name)

        # Split the plate into experimental, contamination, and blank readings.
        test = plate_group.loc[
            (plate_group['Blank'] == False) & (plate_group['reading'] != 'contam')
        ]
        contam = plate_group.loc[plate_group['reading'] == 'contam']
        blank = plate_group.loc[plate_group['Blank'] == True]

        pdf_path = output_dir / f'{experiment}_{plate_name}_roboticOD_preliminary.pdf'
        with PdfPages(str(pdf_path)) as pdf:
            # Experimental samples: one page per plotting group.
            for name, sub in test.groupby(['Plotting_group_number', 'Plotting_group_name']):
                plot_title = name[1].replace(r"\n", "_")
                png_name = f"{plate_name}_{plot_title.replace(' ', '_')}.png"
                plot_OD_replicates(
                    sub, subtract_background=False, blank=False,
                    yscale='log', append_title=name[1].replace(r"\n", "\n"),
                    pdf=pdf, png=True, png_path=str(plot_dir / png_name),
                )

            # Contamination readings (taken before inoculation).
            try:
                plot_OD_contam(
                    contam, subtract_background=False, yscale='log',
                    append_title='Plate OD before inoculation',
                    pdf=pdf, png=True, png_path=str(plot_dir / f'{plate_name}_contam.png'),
                )
            except:
                logger.warning('Plotting contam readings failed.')

            # Blank / media-only wells.
            try:
                plot_OD_replicates(
                    blank, subtract_background=False, blank=True,
                    yscale='log', append_title='',
                    pdf=pdf, png=True, png_path=str(plot_dir / f'{plate_name}_blank.png'),
                )
            except:
                logger.warning('Plotting blank wells failed.')

        # Free the figures created for this plate before moving on.
        plt.close('all')
        logger.info('Wrote plate PDF %s', pdf_path)
        pdf_paths.append(pdf_path)

    return pdf_paths


def main():
    """Main entry point."""
    args = parse_args()
    logger = configure_logging()

    data_dir = Path(args.data_dir).resolve()
    no_layout = args.plate_layout == NO_LAYOUT_SENTINEL
    plate_layout = None if no_layout else Path(args.plate_layout).resolve()
    output_dir = Path(args.output_dir).resolve()
    folder_id = args.gdrive_folder_id

    logger.info('Starting robotic OD processing for data in %s', data_dir)

    # ------------------------------------------------------------------
    # Validate inputs
    # ------------------------------------------------------------------
    if not data_dir.exists() or not data_dir.is_dir():
        logger.error('Data directory not found: %s', data_dir)
        raise FileNotFoundError(f'Data directory not found: {data_dir}')
    if not no_layout and not plate_layout.exists():
        logger.error('Plate layout file not found: %s', plate_layout)
        raise FileNotFoundError(f'Plate layout file not found: {plate_layout}')

    output_dir.mkdir(parents=True, exist_ok=True)
    plot_dir = output_dir / 'png_plots'
    plot_dir.mkdir(parents=True, exist_ok=True)

    # ------------------------------------------------------------------
    # 1. Load and verify raw OD data files
    # ------------------------------------------------------------------
    files = load_and_verify_robotic_od_data(str(data_dir), args.fname_pattern)
    logger.info('Verified %d robotic OD data files', len(files))

    # ------------------------------------------------------------------
    # 2. Extract plate-reader files into a dataframe
    # ------------------------------------------------------------------
    data = extract_robotic_od_data_to_df(files, args.fname_pattern)
    logger.info('Extracted %d measurement rows from data files', len(data))

    # ------------------------------------------------------------------
    # 3. Resolve the plate layout (from file, or synthesized per-well)
    # ------------------------------------------------------------------
    if no_layout:
        layout = build_per_well_layout(data)
        logger.info(
            'No plate layout provided ("-"); synthesized a per-well layout '
            '(%d wells across %d plate(s)) — one growth curve per well',
            len(layout), layout['Plate_name'].nunique(),
        )
    else:
        layout = load_and_verify_plate_layout(str(plate_layout))
        logger.info('Loaded and verified plate layout (%d rows)', len(layout))

    # ------------------------------------------------------------------
    # 4. Map plate layout onto the data
    # ------------------------------------------------------------------
    data = map_plate_layout_to_data(data, layout)
    logger.info('Mapped plate layout onto measurement data')

    # ------------------------------------------------------------------
    # 5. Compute background from media-only wells
    # ------------------------------------------------------------------
    data = compute_background(data)
    logger.info('Computed per-plate background values')

    # ------------------------------------------------------------------
    # 6. Correct timestamps (if accurate timestamps are available)
    # ------------------------------------------------------------------
    ats_folder = Path(args.ats_folder).resolve() if args.ats_folder else data_dir / ATS_SUBFOLDER
    ats_csvs = list(ats_folder.glob('*.csv')) if ats_folder.is_dir() else []
    if ats_csvs:
        data = correct_timestamps(data, str(ats_folder))
        logger.info('Corrected timestamps using %d file(s) in %s', len(ats_csvs), ats_folder)
    else:
        logger.warning(
            'No accurate-timestamp CSVs found in %s; skipping timestamp correction. '
            'Timepoints will be based on filename timestamps.',
            ats_folder,
        )

    # ------------------------------------------------------------------
    # 7. Compute inoculation timestamps and timepoints
    # ------------------------------------------------------------------
    if args.skip_inoculation:
        logger.info('Skipping inoculation/timepoint computation (--skip-inoculation)')
    else:
        data = compute_inoculation(data, first_reading_is_blank=args.first_reading_is_blank)
        logger.info(
            'Computed inoculation timestamps and timepoints (first_reading_is_blank=%s)',
            args.first_reading_is_blank,
        )

    # ------------------------------------------------------------------
    # 8. Verify and write the processed CSV
    # ------------------------------------------------------------------
    experiment = infer_experiment_name(data, args.experiment, logger)
    processed_csv = output_dir / f'{experiment}_robotic_OD_processed_preliminary.csv'
    verify_and_write_processed_data(data, output_path=str(processed_csv))
    logger.info('Wrote processed data to %s', processed_csv)

    # ------------------------------------------------------------------
    # 9. Generate growth-curve plots
    # ------------------------------------------------------------------
    pdf_paths = generate_plate_plots(data, output_dir, plot_dir, experiment, logger)
    logger.info('Generated %d plate PDF(s) and PNG plots in %s', len(pdf_paths), plot_dir)

    # ------------------------------------------------------------------
    # 10. Upload results to Google Drive
    # ------------------------------------------------------------------
    if args.no_upload:
        logger.info('Skipping Google Drive uploads (--no-upload)')
    else:
        # Imported lazily: googledrive loads config/credentials at import time.
        from aisynbiopipeline.limsapi.googledrive import upload_or_replace, upload_folder

        logger.info('Uploading results to Google Drive folder %s', folder_id)
        upload_or_replace(str(processed_csv), folder_id)
        logger.info('Uploaded processed CSV %s', processed_csv.name)
        for pdf_path in pdf_paths:
            upload_or_replace(str(pdf_path), folder_id)
            logger.info('Uploaded plate PDF %s', pdf_path.name)
        upload_folder(str(plot_dir), folder_id)
        logger.info('Uploaded PNG plot folder %s', plot_dir)

    logger.info('Robotic OD processing completed successfully')


if __name__ == '__main__':
    main()
