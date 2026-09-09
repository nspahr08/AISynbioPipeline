"""
Robotic ALE data processing module.
"""

import pandas as pd
from pathlib import Path
import shutil
import re
import os
import warnings
from datetime import datetime


PLATE_WELLS = [f"{row}{col}" for row in "ABCDEFGH" for col in range(1, 13)]
REQUIRED_PLATE_LAYOUT_COLUMNS = [
    'Name', 'Experiment', 'Type', 'Condition', 'Strain_name',
    'Transforming_DNA', 'Protocol', 'Parent_sample', 'Replicate_samples',
    'Plate_name', 'Microtiter_plate_well', 'Plotting_group_number',
    'Plotting_group_name', 'Blank'
]
REQUIRED_PROCESSED_DATA_COLUMNS = [
    'filename', 'experiment', 'file_ID', 'timestamp', 'series',
    'plate_index', 'transfer', 'reading', 'row', 'column', 'od', 'well',
    'datetime', 'Name', 'Experiment', 'Type', 'Condition', 'Strain_name',
    'Transforming_DNA', 'Protocol', 'Parent_sample', 'Replicate_samples',
    'Plate_name', 'Microtiter_plate_well', 'Plotting_group_number',
    'Plotting_group_name', 'Blank', 'background'#, 'innoculation_timestamp', 'timepoint'
    ]


def load_and_verify_plate_layout(path, write_to=None):
    """
    Load and verify a plate layout CSV file.
    
    Validates that the plate layout contains all required columns, properly
    formatted plate wells, and consistent naming across the layout.
    
    Args:
        path: Path to the plate_layout.csv file.
        write_to: Optional path to write the verified dataframe to a new location.
    
    Returns:
        pandas.DataFrame: The verified plate layout dataframe.
    
    Raises:
        ValueError: If the plate layout fails validation checks.
    """
    # Load CSV into dataframe
    df = pd.read_csv(path)
    
    # Required columns
    required_columns = REQUIRED_PLATE_LAYOUT_COLUMNS
    
    # Check for required columns
    missing_columns = set(required_columns) - set(df.columns)
    if missing_columns:
        raise ValueError(f"Missing required columns: {missing_columns}")
    
    # Check that all well values are valid
    invalid_wells = set(df['Microtiter_plate_well']) - set(PLATE_WELLS)
    if invalid_wells:
        raise ValueError(f"Invalid well coordinates found: {sorted(invalid_wells)}")
    
    # Verify each unique 'Plate_name' has 96 unique well coordinates
    wells_per_plate = df.groupby('Plate_name')['Microtiter_plate_well'].nunique()
    invalid_plates = wells_per_plate[wells_per_plate != 96]
    if len(invalid_plates) > 0:
        raise ValueError(
            f"Plates with incorrect number of wells (expected 96): "
            f"{invalid_plates.to_dict()}"
        )
    
    # Verify each 'Plate_name'-'Microtiter_plate_well' combination occurs only once
    plate_well_combo = df.groupby(['Plate_name', 'Microtiter_plate_well']).size()
    duplicates = plate_well_combo[plate_well_combo > 1]
    if len(duplicates) > 0:
        raise ValueError(
            f"Duplicate 'Plate_name'-'Microtiter_plate_well' combinations found: "
            f"{duplicates.to_dict()}"
        )
    
    # Verify each unique 'Name' has a unique 'Plate_name'-'Microtiter_plate_well' combination
    name_location = df.groupby('Name')[['Plate_name', 'Microtiter_plate_well']].nunique()
    duplicates_by_name = name_location[
        (name_location['Plate_name'] > 1) | (name_location['Microtiter_plate_well'] > 1)
    ]
    if len(duplicates_by_name) > 0:
        raise ValueError(
            f"Sample 'Name' values with multiple plate locations: "
            f"{duplicates_by_name.index.tolist()}"
        )
    
    # Write to new location if specified
    if write_to is not None:
        Path(write_to).parent.mkdir(parents=True, exist_ok=True)
        df.to_csv(write_to, index=False)
    
    return df


def build_per_well_layout(data):
    """
    Synthesize a minimal plate layout from the data itself.

    Used when no plate_layout file is supplied: each (plate, well) becomes its
    own sample (``Name``) and its own plotting group, so downstream processing
    and plotting run unchanged and produce one growth curve per well per plate.

    Args:
        data: The extracted robotic OD dataframe (output of
            ``extract_robotic_od_data_to_df``), containing at least the
            ``series`` (plate) and ``well`` columns.

    Returns:
        pandas.DataFrame: A layout dataframe with all
        ``REQUIRED_PLATE_LAYOUT_COLUMNS``, ready for
        ``map_plate_layout_to_data``.
    """
    wells = (
        data[['series', 'well']]
        .drop_duplicates()
        .sort_values(['series', 'well'])
        .reset_index(drop=True)
    )
    tag = wells['series'].astype(str) + '_' + wells['well'].astype(str)
    return pd.DataFrame({
        'Name': tag,
        'Experiment': pd.NA,
        'Type': pd.NA,
        'Condition': pd.NA,
        'Strain_name': tag,  # non-null so no well is treated as a media/background well
        'Transforming_DNA': pd.NA,
        'Protocol': pd.NA,
        'Parent_sample': pd.NA,
        'Replicate_samples': pd.NA,
        'Plate_name': wells['series'],
        'Microtiter_plate_well': wells['well'],
        'Plotting_group_number': range(len(wells)),
        'Plotting_group_name': wells['well'],
        'Blank': False,
    })


def load_and_verify_robotic_od_data(data_folder, file_name_pattern, destination_folder=None, copy_to_destination=False):
    """
    Load and verify robotic OD data files.
    
    Copies all .txt files from the data folder to the destination folder,
    validating that filenames match the pattern and data is properly formatted.
    Copying is optional via the `copy_to_destination` flag.
    
    Args:
        data_folder: Path to the folder containing .txt data files.
        file_name_pattern: Regex pattern that filenames must match with named groups.
        destination_folder: Optional path to copy verified files to. Required if copy_to_destination=True.
        copy_to_destination: Whether to copy validated files to destination folder.
    
    Returns:
        list: List of paths to the copied files, or input files if copy disabled.
    
    Raises:
        ValueError: If any file fails validation.
    """
    data_path = Path(data_folder)
    dest_path = None
    if copy_to_destination:
        if destination_folder is None:
            raise ValueError("destination_folder must be provided when copy_to_destination is True")
        dest_path = Path(destination_folder)
        dest_path.mkdir(parents=True, exist_ok=True)
    
    copied_files = []
    
    # Find all .txt files
    txt_files = list(data_path.glob("*.txt"))
    
    if not txt_files:
        raise ValueError(f"No .txt files found in {data_folder}")
    
    # file_name_pattern is expected to be a regex with named groups
    regex = re.compile(file_name_pattern)
    required_groups = {'experiment', 'timestamp', 'uniqueID', 'series', 'transfer', 'timepoint'}
    if not required_groups.issubset(regex.groupindex.keys()):
        missing = required_groups - set(regex.groupindex.keys())
        raise ValueError(
            f"file_name_pattern regex must define named groups {sorted(required_groups)}, missing: {sorted(missing)}"
        )

    for txt_file in txt_files:
        # Check filename regex and named groups
        match = regex.match(txt_file.name)
        if not match:
            raise ValueError(f"Filename {txt_file.name} does not match regex pattern {file_name_pattern}")
        if not required_groups.issubset(match.groupdict().keys()):
            raise ValueError(
                f"Filename {txt_file.name} match does not include required groups: {sorted(required_groups)}"
            )

        # Load and verify data
        try:
            df = pd.read_csv(txt_file, sep=',', header=None)
        except Exception as e:
            raise ValueError(f"Failed to read {txt_file.name} as comma-delimited: {e}")
        
        # Check shape: 8 rows x 12 columns
        if df.shape != (8, 12):
            raise ValueError(f"File {txt_file.name} has shape {df.shape}, expected (8, 12)")
        
        # Check all values are floats
        try:
            df.astype(float)
        except ValueError as e:
            raise ValueError(f"File {txt_file.name} contains non-numeric values: {e}")
        
        # Copy to destination if requested
        if copy_to_destination:
            dest_file = dest_path / txt_file.name
            shutil.copy2(txt_file, dest_file)
            copied_files.append(str(dest_file))
        else:
            copied_files.append(str(txt_file))

    # Ensure that there are any files that passed validation checks
    if len(copied_files) == 0:
        raise ValueError("No files passed validation checks.")
    
    return copied_files


def extract_robotic_od_data_to_df(
    data_files: list[str],
    fname_pattern,
):
    # Initialize data df
    data = pd.DataFrame()
    
    # Define file pattern for plate reader files
    fname_pattern = re.compile(fname_pattern)
    
    # Read info from plate reader file names and file content into df
    for f in data_files:
        # Initialize row in dataframe
        data_row = {}
        match = fname_pattern.match(os.path.basename(f))
        
        # Parse info contained in plate reader file name
        data_row['filename'] = f
        data_row['experiment'] = str(match.group('experiment')) 
        data_row['file_ID'] = str(match.group('uniqueID'))
        data_row['timestamp'] = int(match.group('timestamp'))
        data_row['series'] = str(match.group('series'))
        data_row['plate_index'] = int(match.group('transfer'))
        data_row['transfer'] = int(match.group('transfer'))
        data_row['reading'] = str(match.group('timepoint'))
   
        # Read plate reader file
        datafile = pd.read_csv(f, header=None)

        # Process plate data
        for row in range(8):
            for col in range(12):
                data_row['row'] = row
                data_row['column'] = col
                data_row['od'] = datafile.iloc[row, col]
                data = pd.concat([data, pd.Series(data_row).to_frame().T])

    data.reset_index(inplace=True, drop=True)

    # Translate row and column numbers to well names
    data['well'] = data.apply(
        lambda x: ['A', 'B', 'C', 'D', 'E', 'F', 'G', 'H'][x['row']] + str(x['column']+1), axis=1
    )
    
    # Translate timestamp into isoformat time
    data['datetime'] = data['timestamp'].apply(
        lambda x: datetime.fromtimestamp(x).isoformat()
    )
    data['datetime'] = pd.to_datetime(data['datetime'])

    return data


EXCLUSION_COLUMNS = ['series', 'file_ID', 'plate_index']


def exclude_obsolete_data(df, exclusions):
    """
    Drop obsolete/duplicate readings produced when the robot restarts a run
    phase from an earlier plate.

    When the robot fails mid-plate and, on restart, resumes a series from an
    earlier plate under a new ``file_ID``, the earlier run phase's overlapping
    readings become obsolete duplicates (data files are never overwritten). This
    removes explicitly listed readings **before** ``compute_cumulative_transfer``
    runs, so each phase's maximum ``plate_index`` — and therefore the cumulative
    transfer offsets — reflect only the kept data. Run it right after
    ``extract_robotic_od_data_to_df`` (while ``plate_index`` still equals the raw
    per-phase index from the filename) and before ``compute_cumulative_transfer``.

    Args:
        df: Extracted robotic OD dataframe (output of
            ``extract_robotic_od_data_to_df``), with ``series``, ``file_ID`` and
            ``plate_index`` columns.
        exclusions: Rows to drop, as a pandas.DataFrame, a path to a CSV
            (str/Path), or None. Must have columns ``series``, ``file_ID`` and
            ``plate_index``. Each row drops all readings matching
            ``(series, file_ID, plate_index)``; a blank/NA ``plate_index`` drops
            every reading of that ``(series, file_ID)`` run phase. None or an
            empty table is a no-op.

    Returns:
        pandas.DataFrame: ``df`` with the matching rows removed (index reset).
        All columns, including the raw ``plate_index``, are otherwise unchanged.

    Raises:
        ValueError: If ``exclusions`` is missing a required column.
    """
    if exclusions is None:
        return df
    if isinstance(exclusions, (str, Path)):
        exclusions = pd.read_csv(exclusions)
    if len(exclusions) == 0:
        return df

    missing = set(EXCLUSION_COLUMNS) - set(exclusions.columns)
    if missing:
        raise ValueError(
            f"exclusions is missing required columns: {sorted(missing)}"
        )

    SEP = '\x00'

    def as_key(s):
        # Extracted columns can be object dtype; compare as stripped strings.
        return s.astype(str).str.strip()

    # Keys over the data: a whole-phase key (series, file_ID) and a per-plate
    # triple key (series, file_ID, plate_index).
    df_phase = as_key(df['series']) + SEP + as_key(df['file_ID'])
    df_triple = (
        df_phase + SEP
        + pd.to_numeric(df['plate_index'], errors='coerce').astype('Int64').astype(str)
    )

    # Split the exclusions: blank plate_index -> whole-phase drop; otherwise a
    # specific (series, file_ID, plate_index) triple.
    ex_s = as_key(exclusions['series'])
    ex_f = as_key(exclusions['file_ID'])
    ex_p = pd.to_numeric(exclusions['plate_index'], errors='coerce')
    drop_phase_keys = set(ex_s[ex_p.isna()] + SEP + ex_f[ex_p.isna()])
    drop_triple_keys = set(
        ex_s[ex_p.notna()] + SEP + ex_f[ex_p.notna()] + SEP
        + ex_p[ex_p.notna()].astype(int).astype(str)
    )

    # Warn on exclusion rows that match nothing (likely a mistyped
    # file_ID / plate_index), so silent no-ops don't hide user error.
    phase_set = set(df_phase)
    triple_set = set(df_triple)
    unmatched = (
        [k for k in drop_phase_keys if k not in phase_set]
        + [k for k in drop_triple_keys if k not in triple_set]
    )
    if unmatched:
        warnings.warn(
            "exclude_obsolete_data: %d exclusion(s) matched no readings "
            "(check series/file_ID/plate_index): %s"
            % (len(unmatched), sorted(k.replace(SEP, '|') for k in unmatched))
        )

    drop = df_phase.isin(drop_phase_keys) | df_triple.isin(drop_triple_keys)
    return df.loc[~drop].reset_index(drop=True)


def compute_cumulative_transfer(df):
    """
    Overwrite ``transfer`` with a cumulative transfer number that is
    continuous across robot run-phase restarts.

    A dataset may contain multiple ``series`` (plates) that run in parallel and
    may be on different transfers; each continuous run phase of a series has its
    own unique ``file_ID``, and on a restart the robot resets that series'
    within-phase index (``plate_index``) back to 1. The cumulative transfer is
    therefore computed **independently per series**: within each
    ``(experiment, series)`` the run phases are ordered by their earliest
    ``timestamp`` and each phase is offset by the total number of transfers
    completed in that series' earlier phases (the sum of every earlier phase's
    maximum ``plate_index``). ``plate_index`` is left untouched as the raw
    per-phase index. When a series has a single run phase, its ``transfer`` is
    unchanged.
    """
    # The extracted dataframe is built from per-row Series, so timestamp /
    # plate_index can arrive as object dtype; coerce before numeric groupby ops.
    phases = (
        df.assign(_ts=pd.to_numeric(df['timestamp']),
                  _plate_index=pd.to_numeric(df['plate_index']))
          .groupby(['experiment', 'series', 'file_ID'])
          .agg(start=('_ts', 'min'),
               phase_transfers=('_plate_index', 'max'))
          .reset_index()
          .sort_values(['experiment', 'series', 'start'])
    )
    # Offset = cumulative transfers of all *earlier* run phases of the same
    # series (series run in parallel and are numbered independently).
    phases['offset'] = (
        phases.groupby(['experiment', 'series'])['phase_transfers'].cumsum()
        - phases['phase_transfers']
    )
    df = df.merge(phases[['experiment', 'series', 'file_ID', 'offset']],
                  on=['experiment', 'series', 'file_ID'], how='left')
    df['transfer'] = df['offset'] + pd.to_numeric(df['plate_index'])
    df.drop(columns=['offset'], inplace=True)
    return df


def map_plate_layout_to_data(robotic_od_data_df, verified_plate_layout_df):
    df = robotic_od_data_df.merge(
        verified_plate_layout_df,
        left_on=['series', 'well'],
        right_on=['Plate_name', 'Microtiter_plate_well'],
        how='left'
        )
    return df


def compute_background(df):  # DOUBLE CHECK THAT THIS IS CORRECT!!!
    
    # Calculate a background value for each plate reader measurement
    # (based on the wells that only contain media)
    
    df['background'] = pd.NA
    df['background'] = df.groupby(
        ['experiment', 'series', 'plate_index', 'timestamp']
        )['od'].transform(
        lambda x: x[df.loc[x.index, 'Strain_name'].isna()].mean()
        )
    
    return df


def compute_inoculation(df, first_reading_is_blank=False):
    """
    Assign an inoculation timestamp to each reading and compute the
    timepoint (in hours) of every reading relative to it.

    The inoculation timestamp is the oldest timestamp within each
    ``(experiment, series, Name, transfer)`` group, where ``transfer`` is the
    cumulative transfer number (see ``compute_cumulative_transfer``) so that
    run phases separated by a robot restart are not merged. When
    ``first_reading_is_blank`` is True the oldest reading of each group
    was taken before inoculation (a blank/media reading) and is skipped:
    the second-oldest timestamp is used as the inoculation timestamp
    instead. Blank readings therefore end up with a negative timepoint.
    Groups with only a single timestamp fall back to that timestamp.
    """

    if first_reading_is_blank:
        def inoc_time_function(x):
            unique_times = x.drop_duplicates().sort_values()
            # Can't skip the first reading if it's the only one.
            if len(unique_times) == 1:
                return unique_times.iloc[0]
            return unique_times.iloc[1]
    else:
        def inoc_time_function(x):
            return x.min()

    df['inoculation_timestamp'] = pd.NA
    live_t = df['reading'] != 'contam'  # Only consider readings taken at or after inoculation
    df.loc[live_t, 'inoculation_timestamp'] = df.loc[live_t].groupby(
            ['experiment', 'series', 'Name', 'transfer']
            )['datetime'].transform(inoc_time_function)

    def calc_timepoint(time_0, time):
        # time_0/time may be pandas Timestamps or ISO-format strings;
        # pd.Timestamp handles both.
        if pd.isna(time_0) or pd.isna(time):
            return pd.NA
        delta = pd.Timestamp(time) - pd.Timestamp(time_0)
        return delta.total_seconds() / 3600

    df['timepoint'] = df.apply(
        lambda x: calc_timepoint(x['inoculation_timestamp'], x['datetime']),
        axis=1
    )

    return df


def correct_timestamps(df, path_to_ats_folder):
    # Accurate timestamps become available after completion of the robotic run.
    ats_df = pd.DataFrame()
    for filename in os.listdir(path_to_ats_folder):
        if filename.endswith('.csv'):
            ats_df = pd.concat([ats_df, pd.read_csv(os.path.join(path_to_ats_folder, filename))])

    # Remove readings files for which there are no accurate timestamps
    df['file_basename'] = df['filename'].transform(lambda x: os.path.basename(x))
    df = pd.merge(df, ats_df, left_on='file_basename', right_on='bmg filename', how='outer')
    df = df.dropna(subset=['bmg filename'])
    df.drop(columns=['datetime'], inplace=True)
    
    df['utc timestamp'].transform(lambda x: datetime.strptime(x, '%Y-%m-%d %H:%M:%S.%f'))
    df.rename(columns={'utc timestamp': 'datetime'}, inplace=True)
    df['datetime'] = pd.to_datetime(df['datetime'])

    return df


def verify_and_write_processed_data(df, output_path=None):
    # Verify that all required columns are present
    for col in REQUIRED_PROCESSED_DATA_COLUMNS:
        if col not in df.columns:
            raise ValueError(f"Column '{col}' is missing from the processed data.")

    if output_path:
        Path(output_path).parent.mkdir(parents=True, exist_ok=True)
        df.to_csv(output_path, index=False)
