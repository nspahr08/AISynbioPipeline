import os
from pathlib import Path
import json
from Bio import SeqIO


def list_reference_genomes() -> list:
    """List all available reference genomes."""
    return os.listdir(get_ref_genomes_path())


def get_ref_genomes_path() -> str:
    """Get REF_GENOMES path from config.json file."""
    config_path = Path(__file__).parent / "config.json"
    # Load configuration
    with open(config_path, 'r') as f:
        config = json.load(f)
        ref_genomes_path = config['REF_GENOMES']
    return ref_genomes_path


def genomic_region_from_features(genbank_file, feature1, feature2):
    """
    Given a GenBank file and two feature identifiers, return the genomic
    start and stop loci spanning both features.

    Parameters
    ----------
    genbank_file : str
        Path to GenBank file.
    feature1 : str
        Identifier for first feature (e.g., gene name or locus_tag).
    feature2 : str
        Identifier for second feature.

    Returns
    -------
    tuple[int, int]
        (start, stop) genomic coordinates (1-based, inclusive).

    Raises
    ------
    ValueError
        If one or both features are not found.
    """

    record = SeqIO.read(genbank_file, "genbank")

    feature_coords = {}

    for feature in record.features:
        qualifiers = feature.qualifiers

        # Collect all qualifier values into a flat list of strings
        qualifier_values = []
        for values in qualifiers.values():
            qualifier_values.extend(values)

        for target in (feature1, feature2):
            if target in qualifier_values and target not in feature_coords:
                start = int(feature.location.start) + 1  # convert to 1-based
                end = int(feature.location.end)          # end is already inclusive
                feature_coords[target] = (start, end)

    missing = {feature1, feature2} - feature_coords.keys()
    if missing:
        raise ValueError(f"Feature(s) not found in GenBank file: {', '.join(missing)}")

    starts, ends = zip(*feature_coords.values())
    return record.name, min(starts), max(ends)


def get_genome_length(genbank_file):
    record = SeqIO.read(genbank_file, "genbank")
    genome_length = len(record.seq)
    return genome_length
