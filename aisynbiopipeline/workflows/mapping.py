import os
import subprocess
import tempfile
from Bio import SeqIO
import shutil
# from binfo_utils import convert_gbk_to_gff3
import pysam
from pathlib import Path


def map_reads(fwd_reads, reference, output_dir, rvs_reads=None, keep_index=False, index_dir=None, sample_name=None):
    
    if not Path(reference).exists():
        raise FileNotFoundError(
                f"Reference file does not exist: {reference}.")

    os.makedirs(output_dir, exist_ok=True)
    
    temp_dir = tempfile.mkdtemp()
    bt2_index = None
    # If an index directory was provided, check for an existing index there first
    if index_dir:
        os.makedirs(index_dir, exist_ok=True)
        prefix = os.path.join(index_dir, 'reference')
        # Look for any files that start with the index prefix (bowtie2 index files)
        from glob import glob
        existing = len(glob(prefix + '*')) > 0
        if existing:
            print(f"Found existing bowtie2 index in {index_dir}, using it.")
            bt2_index = prefix
        else:
            # No existing index in index_dir: create one there if user asked to keep,
            # otherwise create in a temporary directory
            if keep_index:
                bt2_index = index_reference(reference, index_dir=index_dir)
            else:
                bt2_index = index_reference(reference, index_dir=temp_dir)
    else:
        # No index_dir provided: create index in temp or in place per keep_index
        if keep_index:
            # keep_index requested but no index_dir given: create in temp_dir but warn
            print("keep_index=True but no index_dir provided; creating index in temporary dir.")
            bt2_index = index_reference(reference, index_dir=temp_dir)
        else:
            bt2_index = index_reference(reference, index_dir=temp_dir)
    sam_file = map_to_indexed_ref(fwd_reads, bt2_index, output_dir, rvs_reads=rvs_reads, sample_name=sample_name)
    bam_file = sort_and_index_bam(sam_file)
    if temp_dir and os.path.exists(temp_dir):
        shutil.rmtree(temp_dir)
    return bam_file


def index_reference(reference: str, index_dir):
    # Ensure index directory exists
    os.makedirs(index_dir, exist_ok=True)
    print(f"Building bowtie2 index in {index_dir} from reference {reference}")
    # Determine file type
    ref_ext = os.path.splitext(reference)[1].lower()
    fasta_path = reference
    if ref_ext in ['.gb', '.gbk', '.genbank']:
        fasta_path = os.path.join(index_dir, 'reference.fasta')
        SeqIO.convert(reference, 'genbank', fasta_path, 'fasta')
    index = os.path.join(index_dir, 'reference')
    subprocess.run([
        'bowtie2-build', fasta_path, index
    ], check=True)
    return index


def map_to_indexed_ref(
        fwd_reads, bowtie2_index, output_dir, rvs_reads=None, sample_name='output'):
    """
    Map reads to an indexed reference using bowtie2.
    
    Args:
        fwd_reads: Forward reads file path(s), single or list
        bowtie2_index: Path to bowtie2 index (prefix only)
        output_dir: Directory for output files
        rvs_reads: Reverse reads file path(s), single or list. If None, treats fwd_reads as unpaired.
        sample_name: Prefix for output files
    """
    # Convert inputs to lists if they're strings
    if isinstance(fwd_reads, str):
        fwd_reads = [fwd_reads]
    if rvs_reads is not None and isinstance(rvs_reads, str):
        rvs_reads = [rvs_reads]
    
    # Validate read file counts
    if rvs_reads is not None:
        if len(fwd_reads) != len(rvs_reads):
            raise ValueError("Number of forward and reverse read files must match")
        read_type = "paired-end"
    else:
        read_type = "unpaired (single-end)"
        
    print(f"Mapping {read_type} reads to reference {bowtie2_index}")
    print(f"  Forward: {fwd_reads}")
    if rvs_reads:
        print(f"  Reverse: {rvs_reads}")
    
    output_sam = os.path.join(output_dir, sample_name + '.sam')
    log_file = os.path.join(output_dir, sample_name + '_bowtie2.log')
    
    # Build command with multiple input files
    cmd = [
        'bowtie2',
        '-x', bowtie2_index,
    ]
    
    if rvs_reads:
        # Paired-end reads
        cmd.extend([
            '-1', ','.join(fwd_reads),  # bowtie2 accepts comma-separated lists
            '-2', ','.join(rvs_reads),
        ])
    else:
        # Unpaired reads
        cmd.extend([
            '-U', ','.join(fwd_reads),
        ])
    
    cmd.extend([
        '-S', output_sam
    ])
    
    with open(log_file, 'w') as log_fh:
        subprocess.run(cmd, check=True, stderr=log_fh)
    return output_sam


def count_mapped_reads(bam_file):
    cmd = [
        'samtools', 'view',
        '-c',  # count reads in bam file
        '-F', '4',  # filter out reads with 0x0004 bit flag set, i.e. unmapped reads
        bam_file
    ]
    result = subprocess.run(
        cmd,
        check=True,
        capture_output=True,  # captures both stdout and stderr
        text=True  # converts output to string instead of bytes
    )
    # stdout contains the count as a string
    return int(result.stdout.strip())


def parse_bowtie2_log(log_file):
    """
    Parse bowtie2 log file to extract the overall alignment rate.
    
    Args:
        log_file: Path to the bowtie2 log file
        
    Returns:
        float: The overall alignment rate as a percentage, or None if not found
    """
    try:
        with open(log_file, 'r') as f:
            for line in f:
                if "overall alignment rate" in line:
                    # Extract percentage from alignment rate line
                    return float(line.split('%')[0].strip())
    except (FileNotFoundError, ValueError, IndexError):
        return None
    return None


def sort_and_index_bam(sam_file):
    print(f"Sorting and indexing BAM file from {sam_file}")
    output_bam = os.path.splitext(sam_file)[0] + '.sorted.bam'
    # Convert SAM to BAM, sort
    cmd_sort = [
        'samtools', 'sort', '-o', output_bam, sam_file
    ]
    subprocess.run(cmd_sort, check=True)
    # Index BAM
    cmd_index = [
        'samtools', 'index', output_bam
    ]
    subprocess.run(cmd_index, check=True)
    return output_bam


def run_fadu(bam_file, reference_file, output_dir, fadu_folder=None):
    
    temp_dir = None

    if fadu_folder is None:
        fadu_folder = '/Users/nataschaspahr/code/FADU/'

    reference_file_ext = os.path.splitext(reference_file)[1].lower()

    if reference_file_ext in ['.gb', '.gbk', '.genbank']:
        temp_dir = tempfile.mkdtemp()
        gff3 = convert_gbk_to_gff3(reference_file, temp_dir+'/reference.gff3')

    elif reference_file_ext not in ['.gff3', '.gff']:
        msg = ("Reference file must be in GenBank (.gb, .gbk) "
               "or GFF3 (.gff3) format.")
        raise ValueError(msg)

    else:
        gff3 = reference_file

    fadu_cmd = [
        'julia',
        f'--project={fadu_folder}/fadu_pkgs',
        f'{fadu_folder}/fadu.jl',
        '-M',  # remove multimapping reads
        '-g', gff3,
        '-b', bam_file,
        '-o', output_dir,
        '-f', 'gene',
        '-a', 'ID'  # feature name tag in gff3 to use
    ]
    
    print(f"Running FADU with command: {' '.join(fadu_cmd)}")
    subprocess.run(fadu_cmd, check=True)

    if temp_dir is not None:
        shutil.rmtree(temp_dir)

    return output_dir


def map_and_feature_count(
        fwd_reads,
        reference,
        output_dir,
        rvs_reads=None,
        keep_index=False,
        index_dir=None,
        sample_name=None,
        fadu_folder=None):
    """
    Maps reads to a reference and performs feature counting using FADU.
    Supports both paired-end and unpaired (single-end) reads.
    """
    if not os.path.exists(output_dir):
        os.makedirs(output_dir)

    bam_file = map_reads(
        fwd_reads,
        reference,
        output_dir,
        rvs_reads=rvs_reads,
        keep_index=keep_index,
        index_dir=index_dir,
        sample_name=sample_name
    )
    
    output_dir = run_fadu(
        bam_file,
        reference,
        output_dir,
        fadu_folder=fadu_folder
    )

    return output_dir


# class PileupCol:
#     """Set of basecalls from reads mapped to 1-bp locus in a reference genome.
#     """

#     def __init__(
#         self,
#         bam_path: [Path|str],
#         locus: int
#     ):
#         self.bam_path = bam_path
#         self.locus = locus
        
#         if not bam_path.exists():
#             raise FileNotFoundError(f"bam_path does not exist: {self.bam_path}")

#         samfile = pysam.AlignmentFile(self.bam_path, "rb")
#         self.reference_name = samfile.get_reference_name(0)
#         if samfile.lengths[0] < self.locus:
#             raise ValueError(f"Locus must be smaller or equal to length of {self.reference_name}.")

#         iter = samfile.pileup(
#             reference=self.reference_name,
#             start=self.locus-1,
#             stop=self.locus,
#             truncate=True
#         )
        
#         col = next(iter)

#         basecalls = col.get_query_sequences()
#         self.basecalls = [x.upper() for x in basecalls]

class PileupCol:
    """Set of basecalls from reads mapped to a locus in a reference genome.
    """

    def __init__(
        self,
        bam_path: [Path|str],
        locus: tuple
    ):
        self.bam_path = bam_path
        self.locus = locus
        self.start = self.locus[0]
        self.stop = self.locus[1]
        
        if not bam_path.exists():
            raise FileNotFoundError(f"bam_path does not exist: {self.bam_path}")

        samfile = pysam.AlignmentFile(self.bam_path, "rb")
        self.reference_name = samfile.get_reference_name(0)
        if samfile.lengths[0] < self.stop:
            raise ValueError(f"Locus must be smaller or equal to length of {self.reference_name}.")

        iter = samfile.pileup(
            reference=self.reference_name,
            start=self.start-1,
            stop=self.stop,
            truncate=True
        )

        basecalls = []
        for i in iter:
            basecalls.append(i.get_query_sequences())

        basecalls = [''.join(group) for group in zip(*basecalls)]
        self.basecalls = [x.upper() for x in basecalls]
        