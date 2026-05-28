import gzip
from Bio import SeqIO
from Bio.Seq import Seq
import os
import re
import pandas as pd
import glob
import json


def parse_illumina_fastq_filename(filepath: str) -> tuple[str, str]:
    """
    Parse an Illumina fastq filename to extract sample number, lane number, and read direction.
    Handles both gzipped (.fastq.gz) and non-gzipped (.fastq) files.
    
    Args:
        filepath (str): Path to the fastq file
            Examples: 
            - 'Data/Intensities/BaseCalls/SampleName_SampleNameContinued_S1_L001_R1_001.fastq.gz'
            - 'Data/Intensities/BaseCalls/SampleName_SampleNameContinued_S1_L001_R1_001.fastq'
    
    Returns:
        tuple[str, str]: (sample_name, lane, read)
            Example: ('SampleName_SampleNameContinued', '001', 'R1')
            
    Raises:
        ValueError: If the filename doesn't match expected Illumina format
    """
    
    # Get just the filename from the path
    filename = os.path.basename(filepath)
    
    # Pattern matches:
    # - Any characters up to _S\d+ (sample name)
    # - _S\d+ (sample number)
    # - _L\d{3} (lane number)
    # - _(R[12]) (read direction)
    # - _\d{3} (always 001)
    # - \.fastq(\.gz)? (file extension, optional gz)
    pattern = r'(.+)_S(\d+)_L(\d{3})_(R[12])_\d{3}\w*.fastq(?:\.gz)?'
    
    match = re.match(pattern, filename)
    if not match:
        raise ValueError(f"Filename {filename} doesn't match expected Illumina format")
    
    sample_name, sample_number, lane, read = match.groups()
    return sample_name, int(sample_number), int(lane), read


def create_manifest(folder: str, platform: str = 'illumina') -> pd.DataFrame:

    if not os.path.exists(folder):
        raise FileNotFoundError(f'Folder missing: {folder}')
    
    if platform == 'illumina':
        files = glob.glob(os.path.join(folder, '*.fastq*'))
        data = []
        for file in files:
            sample_name = parse_illumina_fastq_filename(file)[0]
            sample_number = parse_illumina_fastq_filename(file)[1]
            lane  = parse_illumina_fastq_filename(file)[2]
            read  = parse_illumina_fastq_filename(file)[3]
            if read == 'R1':
                data.append({
                    'sample_name': sample_name,
                    'sample_number': sample_number,
                    'fwd_fastq': file,
                    'rvs_fastq': None
                })
            elif read == 'R2':
                data.append({
                    'sample_name': sample_name,
                    'sample_number': sample_number,
                    'fwd_fastq': None,
                    'rvs_fastq': file
                })
        df = pd.DataFrame(data)
        manifest = df.groupby(['sample_name', 'sample_number'], as_index=False).agg({
            'fwd_fastq': lambda x: [x for x in list(x) if x != None][0],
            'rvs_fastq': lambda x: [x for x in list(x) if x != None][0]
        })
        return manifest.sort_values('sample_name')

    elif platform == 'nanopore':
        data = []
        files = glob.glob(os.path.join(folder, '*.fastq*'))
        for file in files:
            sample_name = os.path.basename(file).split('.')[0].split('_')[0]
            data.append({'sample_name': sample_name, 'fastq': file}) 
        manifest = pd.DataFrame(data)

        return manifest.sort_values('sample_name')

    elif platform == 'plasmidsaurus_hybrid':
        data = []
        files = glob.glob(os.path.join(folder, '*.fastq.gz'))
        sample_files = {}
        for file in files:
            basename = os.path.basename(file)
            sample_name = basename.replace('_illumina_R1.fastq.gz', '')\
                .replace('_illumina_R2.fastq.gz', '')\
                .replace('_nanopore.fastq.gz', '')\
                .replace('_illumina_R1_trimmed.fastq.gz', '')\
                .replace('_illumina_R2_trimmed.fastq.gz', '')\
                .replace('_nanopore_filtered.fastq.gz', '')
            if sample_name not in sample_files:
                sample_files[sample_name] = {'sample_name': sample_name}
            if file.endswith('_illumina_R1.fastq.gz') or file.endswith('_illumina_R1_trimmed.fastq.gz'):
                sample_files[sample_name]['fwd_fastq'] = file
            elif file.endswith('_illumina_R2.fastq.gz') or file.endswith('_illumina_R2_trimmed.fastq.gz'):
                sample_files[sample_name]['rvs_fastq'] = file
            elif file.endswith('_nanopore.fastq.gz') or file.endswith('_nanopore_filtered.fastq.gz'):
                sample_files[sample_name]['nanopore_fastq'] = file
        data = list(sample_files.values())
        manifest = pd.DataFrame(data)
        return manifest.sort_values('sample_name')

    elif platform == 'plasmidsaurus_illumina':
        data = []
        files = glob.glob(os.path.join(folder, '*.fastq.gz'))
        sample_files = {}
        for file in files:
            basename = os.path.basename(file)
            sample_name = basename.replace('_R1.fastq.gz', '')\
                .replace('_R2.fastq.gz', '')\
                .replace('_R1_trimmed.fastq.gz', '')\
                .replace('_R2_trimmed.fastq.gz', '')
            if sample_name not in sample_files:
                sample_files[sample_name] = {'sample_name': sample_name}
            if file.endswith('_R1.fastq.gz') or file.endswith('_R1_trimmed.fastq.gz'):
                sample_files[sample_name]['fwd_fastq'] = file
            elif file.endswith('_R2.fastq.gz') or file.endswith('_R2_trimmed.fastq.gz'):
                sample_files[sample_name]['rvs_fastq'] = file
        data = list(sample_files.values())
        manifest = pd.DataFrame(data)
        return manifest.sort_values('sample_name').reset_index(drop=True)

    elif platform == 'seqcenter_illumina':
        data = []
        files = glob.glob(os.path.join(folder, '*.fastq.gz'))
        sample_files = {}
        for file in files:
            basename = os.path.basename(file)
            sample_name = basename.split('_S')[0]
            if sample_name not in sample_files:
                sample_files[sample_name] = {'sample_name': sample_name}
            if '_R1' in file:
                sample_files[sample_name]['fwd_fastq'] = file
            elif '_R2' in file:
                sample_files[sample_name]['rvs_fastq'] = file
        data = list(sample_files.values())
        manifest = pd.DataFrame(data)
        return manifest.sort_values('sample_name').reset_index(drop=True)
    
    else:
        raise ValueError("Unsupported platform. Use 'illumina', 'nanopore', 'plasmidsaurus_hybrid', or 'plasmidsaurus_illumina'.")