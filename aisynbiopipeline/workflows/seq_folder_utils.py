"""
Module for managing genomic sequencing data folder structures.

This module provides classes and functions to maintain and navigate
a predefined folder structure for sequencing orders, libraries, and samples.
"""

import os
import json
import shutil
from pathlib import Path
from typing import List, Optional, Union, Dict, Any
import pandas as pd


def get_seqorders_path() -> str:
    """
    Retrieve the path to the sequencing orders directory from config.json.
        
    Returns:
        Path object pointing to the sequencing_orders directory
        
    Raises:
        FileNotFoundError: If config.json doesn't exist
        KeyError: If 'sequencing_orders_path' key is missing from config
    """
    config_file = Path(__file__).parent / "config.json"
    if not config_file.exists():
        raise FileNotFoundError(f"Config file not found: {config_path}")
    
    with open(config_file, 'r') as f:
        config = json.load(f)
    
    if 'SEQ_ORDERS' not in config:
        raise KeyError("'sequencing_orders_path' key not found in config.json")
    
    return Path(config['SEQ_ORDERS'])


def list_seqorders() -> List[str]:
    """
    List all sequencing orders in the sequencing_orders directory.
    
    Returns:
        List of sequencing order names (folder names)
    """
    seqorders_path = get_seqorders_path()
    
    if not seqorders_path.exists():
        return []
    
    # Return only directories, not files
    return [d.name for d in seqorders_path.iterdir() if d.is_dir()]


class SeqOrder:
    """
    Represents a sequencing order folder.
    
    A sequencing order contains one or more sequencing libraries.
    """
    
    def __init__(self, name: str, create=False):
        """
        Initialize a SeqOrder object.
        
        Args:
            name: Name of the sequencing order (folder name)
        """
        seqorders_path = get_seqorders_path()
        
        self.name = name
        self.path = seqorders_path / name
        
        # Only create the folder if it doesn't exist and if create=True
        if not self.path.exists() and not create:
            raise FileNotFoundError(
                f"Sequencing order folder does not exist: {self.path}. To create, set create=True")

        if self.path.exists() and create:
            raise ValueError(
                f"Sequencing order folder already exists: {self.path}. To overwrite, delete seqorder, then create anew.")

        if not self.path.exists() and create:
            self.path.mkdir(parents=True)
    
    @property
    def libraries(self) -> List[Path]:
        """
        Get paths to all libraries in this sequencing order.
        
        Returns:
            List of Path objects to library folders
        """
        if not self.path.exists():
            return []
        
        return [lib_path for lib_path in self.path.iterdir() 
                if lib_path.is_dir() and ('_Illumina' in lib_path.name or '_Nanopore' in lib_path.name)]
    
    def delete(self):
        """Delete the sequencing order folder and all its contents."""
        if self.path.exists():
            shutil.rmtree(self.path)
        print(f"SeqOrder {self.name} at {self.path} was deleted.")
    
    def rename(self, new_name: str):
        """
        Rename the sequencing order folder and update all library folder names.
        
        Args:
            new_name: New name for the sequencing order
        """
        if not self.path.exists():
            raise FileNotFoundError(f"Sequencing order folder does not exist: {self.path}")
        
        new_path = self.path.parent / new_name
        
        # Rename the main folder
        self.path.rename(new_path)
        self.path = new_path
        self.name = new_name
        
        # # Update library folder names
        # for lib_path in self.libraries:
        #     old_lib_name = lib_path.name
        #     # Extract platform suffix
        #     if '_Illumina' in old_lib_name:
        #         platform = 'Illumina'
        #     elif '_Nanopore' in old_lib_name:
        #         platform = 'Nanopore'
        #     else:
        #         continue  # Skip if format doesn't match
            
        #     new_lib_name = f"{new_name}_{platform}"
        #     new_lib_path = self.path / new_lib_name
        #     lib_path.rename(new_lib_path)


class Library:
    """
    Represents a sequencing library folder (Illumina or Nanopore).
    
    A library contains sample data at different processing stages.
    """
    
    def __init__(self, seqorder: Union[SeqOrder, str], platform: str, name = None, create=False, subfolders=False):
        """
        Initialize a Library object.
        
        Args:
            seqorder: SeqOrder object or name of sequencing order
            platform: Sequencing platform ('Illumina' or 'Nanopore')
        """
        if isinstance(seqorder, str):
            seqorders_path = get_seqorders_path()
            seqorder = SeqOrder(seqorder)
        
        if platform not in ['Illumina', 'Nanopore']:
            raise ValueError(f"Platform must be 'Illumina' or 'Nanopore', got: {platform}")
        
        self.seqorder = seqorder
        self.platform = platform
        if not name:
            self.name = f"{seqorder.name}_{platform}"
        else:
            self.name = name
        self.path = seqorder.path / self.name

        # Only create the folder if it doesn't exist and if create=True
        if not self.path.exists() and not create:
            raise FileNotFoundError(
                f"Library folder does not exist: {self.path}. To create, set create=True")

        if self.path.exists() and create:
            raise ValueError(
                f"Library folder already exists: {self.path}. To overwrite, delete library, then create anew.")
        
        if not self.path.exists() and create:
            self.path.mkdir(parents=True)
        
        # Always create 'received' subfolder
        self.create_subfolder('received')
    
    def create_subfolder(self, subfolder: str):
        """Create subfolder."""
        acceptable = ['received', 'trimmed', 'breseq', 'mapped', 'filtered', 'extract_barcodes']
        if subfolder not in acceptable:
            raise ValueError(
                f"Subfolder name must be among this list: {acceptable}."
            )

        (self.path / subfolder).mkdir(exist_ok=True)
    
    # def delete(self):
    #     """Delete the library folder and all its contents."""
    #     if self.path.exists():
    #         shutil.rmtree(self.path)

    def delete(self, subfolder: str):
        """
        Delete library data.
        
        Args:
            subfolder: Subfolder to delete ('all', 'received', 'trimmed', 'filtered', 'breseq', 'mapped')
        """
        acceptable = ['all', 'received', 'trimmed', 'filtered', 'breseq', 'mapped']
        if subfolder not in acceptable:
            raise ValueError(
                f"Subfolder name must be among this list: {acceptable}."
            )
        if subfolder == 'all':
            for folder in os.listdir(self.path):
                shutil.rmtree(self.path / folder) 
        else:
            shutil.rmtree(self.path / subfolder)
    
    def rename(self, new_name: str):
        """
        Rename the library folder.
        
        Args:
            new_name: New name for the library (should include platform suffix)
        """
        if not self.path.exists():
            raise FileNotFoundError(f"Library folder does not exist: {self.path}")
        
        new_path = self.path.parent / new_name
        self.path.rename(new_path)
        self.path = new_path
        self.name = new_name
    
    def create_manifest(self, folder: str) -> pd.DataFrame:
        """
        Create a manifest table of samples and their fastq files for a given folder.
        
        Args:
            folder: Folder name ('received', 'trimmed', 'filtered')
            
        Returns:
            pandas DataFrame with columns: sample_name, fastq_files (and R1/R2 for Illumina)
        """
        folder_path = self.path / folder
        if not folder_path.exists():
            raise FileNotFoundError(f"Folder does not exist: {folder_path}")
        
        # Find all fastq files
        fastq_files = list(folder_path.glob("*.fastq*"))
        
        if not fastq_files:
            return pd.DataFrame(columns=['sample_name', 'fastq_files'])
        
        # Extract sample names from fastq files
        # Assumes format: sample_name_R1.fastq.gz or sample_name.fastq.gz
        samples_dict: Dict[str, Dict[str, Any]] = {}
        
        for fastq_file in fastq_files:
            # Remove common fastq extensions
            base_name = fastq_file.stem
            if base_name.endswith('.fastq'):
                base_name = base_name[:-6]
            
            # Check for paired-end indicators
            if self.platform == 'Illumina':
                # Look for _R1, _R2, _1, _2 patterns
                if '_R1' in base_name or '_1' in base_name:
                    sample_name = base_name.replace('_R1', '').replace('_1', '').rstrip('_').replace('_illumina', '').replace('_trimmed', "")
                    if sample_name not in samples_dict:
                        samples_dict[sample_name] = {'sample_name': sample_name, 'R1': None, 'R2': None}
                    samples_dict[sample_name]['R1'] = str(fastq_file)
                elif '_R2' in base_name or '_2' in base_name:
                    sample_name = base_name.replace('_R2', '').replace('_2', '').rstrip('_').replace('_illumina', '').replace('_trimmed', "")
                    if sample_name not in samples_dict:
                        samples_dict[sample_name] = {'sample_name': sample_name, 'R1': None, 'R2': None}
                    samples_dict[sample_name]['R2'] = str(fastq_file)
                else:
                    # Single-end or unpaired
                    sample_name = base_name.replace('_illumina', '')
                    if sample_name not in samples_dict:
                        samples_dict[sample_name] = {'sample_name': sample_name, 'fastq_file': None}
                    samples_dict[sample_name]['fastq_file'] = str(fastq_file)
            else:  # Nanopore
                # Nanopore typically has single fastq files
                sample_name = base_name.replace('_nanopore', '')
                if sample_name not in samples_dict:
                    samples_dict[sample_name] = {'sample_name': sample_name, 'fastq_file': None}
                samples_dict[sample_name]['fastq_file'] = str(fastq_file)
        
        # Convert to DataFrame
        data = list(samples_dict.values())
        df = pd.DataFrame(data).sort_values('sample_name')
        
        return df.reset_index(drop=True)

        
class SeqSample:
    """
    Represents a sequencing sample within a library.
    
    A sample has data at different processing stages (received, trimmed, filtered, etc.)
    """
    
    def __init__(self, library: Union[Library, tuple], sample_name: str):
        """
        Initialize a SeqSample object.
        
        Args:
            library: Library object or tuple of (seqorder_name, platform)
            sample_name: Name of the sample
        """
        # Enforce allowed types
        if not isinstance(library, (Library, tuple)):
            raise TypeError(
                f"library must be a Library or tuple, not {type(library).__name__}"
            )
        if isinstance(library, tuple):
            seqorder_name, platform = library
            library = Library(seqorder_name, platform)
        
        self.library = library
        self.sample_name = sample_name
    
    @property
    def received(self) -> List[Path]:
        """Get paths to received fastq files for this sample."""
        return self._get_fastq_files('received')
    
    @property
    def trimmed(self) -> List[Path]:
        """Get paths to trimmed fastq files for this sample (Illumina only)."""
        if self.library.platform != 'Illumina':
            return []
        return self._get_fastq_files('trimmed')

    @property
    def trimmed_fastp(self) -> List[Path]:
        """Get paths to fastp files for this sample in trimmed folder (Illumina only)."""
        if self.library.platform != 'Illumina':
            return []
        return self._get_fastp_files('trimmed')
    
    @property
    def filtered(self) -> List[Path]:
        """Get paths to filtered fastq files for this sample (Nanopore only)."""
        if self.library.platform != 'Nanopore':
            return []
        return self._get_fastq_files('filtered')
    
    @property
    def breseq(self) -> Path:
        """Get path to breseq folder for this sample (Illumina only)."""
        if self.library.platform != 'Illumina':
            return None
        breseq_path = self.library.path / 'breseq' / self.sample_name
        # breseq_path.mkdir(parents=True, exist_ok=True)
        return breseq_path
    
    @property
    def mapped(self) -> Path:
        """Get path to mapped folder for this sample (Illumina only)."""
        if self.library.platform != 'Illumina':
            return None
        mapped_path = self.library.path / 'mapped' / self.sample_name
        # mapped_path.mkdir(parents=True, exist_ok=True)
        return mapped_path
    
    def _get_fastq_files(self, folder: str) -> List[Path]:
        """Get fastq files for this sample in a given folder."""
        folder_path = self.library.path / folder
        if not folder_path.exists():
            return []
        
        # Look for fastq files containing the sample name
        pattern = f"{self.sample_name}*.fastq*"
        fastq_files = list(folder_path.glob(pattern))
        
        # Sort to ensure consistent ordering (R1 before R2 if paired-end)
        return sorted(fastq_files)

    def _get_fastp_files(self, folder: str) -> List[Path]:
        """Get fastp files for this sample in a given folder."""
        folder_path = self.library.path / folder
        if not folder_path.exists():
            return []
        
        # Look for fastp files containing the sample name
        pattern = f"{self.sample_name}*_fastp*"
        fastp_files = list(folder_path.glob(pattern))
        
        return fastp_files
    
    def delete(self, subfolder: str):
        """
        Delete sample data..
        
        Args:
            subfolder: Subfolder to delete ('all', 'received', 'trimmed', 'filtered', 'breseq', 'mapped')
                       If None, deletes all sample-related data
        """
        if subfolder == 'all':
            # Delete all sample-related data
            for subfolder_name in ['received', 'trimmed', 'filtered']:
                try:
                    self.delete(subfolder_name)
                except:
                    pass
            # Delete breseq and mapped if they exist
            if self.library.platform == 'Illumina':
                if self.breseq and self.breseq.exists():
                    shutil.rmtree(self.breseq)
                if self.mapped and self.mapped.exists():
                    shutil.rmtree(self.mapped)
            return        

        if subfolder == 'received':
            # Delete fastq files in received folder
            for fastq_file in self.received:
                if fastq_file.exists():
                    fastq_file.unlink()
                    
        elif subfolder == 'trimmed':
            # Delete fastq files in trimmed folder
            for fastq_file in self.trimmed:
                if fastq_file.exists():
                    fastq_file.unlink()
            # Delete fastp files in trimmed folder
            for fastp_file in self.trimmed_fastp:
                if fastp_file.exists():
                    fastp_file.unlink()
                    
        elif subfolder == 'filtered':
            # Delete fastq files in filtered folder
            for fastq_file in self.filtered:
                if fastq_file.exists():
                    fastq_file.unlink()
                    
        elif subfolder == 'breseq':
            # Delete breseq folder for this sample
            breseq_path = self.breseq
            if breseq_path and breseq_path.exists():
                shutil.rmtree(breseq_path)
                
        elif subfolder == 'mapped':
            # Delete mapped folder for this sample
            mapped_path = self.mapped
            if mapped_path and mapped_path.exists():
                shutil.rmtree(mapped_path)
        else:
            raise ValueError(f"Unknown subfolder: {subfolder}")

    def rename(self, new_name: str):
        """
        Rename the sample. This updates:
        - Fastq file names containing the sample name
        - Breseq subfolder name
        - Mapped subfolder name
        - Any other references to the sample name
        
        Args:
            new_name: New name for the sample
        """
        if not self.library.path.exists():
            raise FileNotFoundError(f"Library folder does not exist: {self.library.path}")
        
        old_name = self.sample_name
        
        # Rename fastq files in received folder
        self._rename_fastq_files('received', old_name, new_name)
        
        # Rename fastq files in trimmed folder (Illumina)
        if self.library.platform == 'Illumina':
            self._rename_fastq_files('trimmed', old_name, new_name)
            
            # Rename breseq folder
            old_breseq_path = self.library.path / 'breseq' / old_name
            if old_breseq_path.exists():
                new_breseq_path = self.library.path / 'breseq' / new_name
                old_breseq_path.rename(new_breseq_path)

            # Rename mapped folder
            old_mapped_path = self.library.path / 'mapped' / old_name
            if old_mapped_path.exists():
                new_mapped_path = self.library.path / 'mapped' / new_name
                old_mapped_path.rename(new_mapped_path)
        
        # Rename fastq files in filtered folder (Nanopore)
        if self.library.platform == 'Nanopore':
            self._rename_fastq_files('filtered', old_name, new_name)
        
        self.sample_name = new_name


    def copy(self, dst_seqorder: SeqOrder):
        """Copy all associated files and folders from this SeqSample
        to a different seqorder, preserving all relative file paths.
        """

        # Copy over each of the subfolders and files in which the seqsample is represented.
        src_seqorder = self.library.seqorder
        
        seqsample_paths = self.received + self.trimmed + self.filtered + [self.breseq] + [self.mapped]
        for src_path in seqsample_paths:
            relative_path = os.path.relpath(src_path, start=src_seqorder.path)
            if os.path.exists(src_path) and os.path.isdir(src_path):
                dst_path = os.path.join(dst_seqorder.path, relative_path)
                os.makedirs(os.path.dirname(dst_path), exist_ok=True)
                shutil.copytree(src_path, dst_path, dirs_exist_ok=True)
            elif os.path.exists(src_path) and not os.path.isdir(src_path):
                dst_path = os.path.join(dst_seqorder.path, relative_path)
                os.makedirs(os.path.dirname(dst_path), exist_ok=True)
                shutil.copy2(src_path, dst_path)
        
        print(f"All associated files and folders of SeqSample {self.sample_name} were copied to {dst_seqorder.path}. Relative file paths were preserved.")
        dst_library = Library(dst_seqorder, self.library.platform, name=self.library.name)
        dst_library.rename(dst_seqorder.name + "_" + self.library.platform)
        new_seqsample = SeqSample(dst_library, self.sample_name)
        
        return new_seqsample
        
    
    def _rename_fastq_files(self, folder: str, old_name: str, new_name: str):
        """Rename fastq files in a given folder."""
        folder_path = self.library.path / folder
        if not folder_path.exists():
            return
        
        # Find all fastq files with the old sample name
        pattern = f"{old_name}*.fastq*"
        fastq_files = folder_path.glob(pattern)
        
        for fastq_file in fastq_files:
            new_file_name = fastq_file.name.replace(old_name, new_name)
            new_file_path = folder_path / new_file_name
            fastq_file.rename(new_file_path)

