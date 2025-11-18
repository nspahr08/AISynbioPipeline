# Jupyter Notebooks for LIMS API

This directory contains Jupyter notebooks demonstrating how to use the LIMS API to query and analyze data from the laboratory information management system.

## Quick Start

### 1. Set Up Environment

If you haven't already set up the conda environment:

```bash
cd ..  # Go to project root
./setup_env.sh
source activate.sh
```

### 2. Start Jupyter

```bash
jupyter notebook
```

This will open a browser window with the Jupyter interface showing all available notebooks.

## Available Notebooks

### APIExamples.ipynb

Comprehensive examples showing how to use the LIMS API, including:

1. Listing available tables
2. Exploring table schemas
3. Querying all records
4. Filtering data
5. Selecting specific columns
6. Limiting results
7. Searching for records
8. Working with related data (samples and measurements)
9. Combining data with pandas
10. Advanced queries with ordering
11. Complex multi-table analysis
12. Best practices and tips

## Helper Functions (util_simple.py)

The `util_simple.py` module provides convenient helper functions for the notebooks:

### Core Functions

- **`query_lims(table, filters, columns, limit, order_by, order_desc)`**
  - Query a table and return a pandas DataFrame
  - Example: `df = query_lims('Samples', filters={'Experiment': 'ALE1b'})`

- **`search_lims(table, column, search_term)`**
  - Search for records containing text
  - Example: `results = search_lims('Strains', 'Name', 'ADP1')`

- **`get_lims_tables()`**
  - Get list of all available tables
  - Example: `tables = get_lims_tables()`

- **`get_lims_schema(table)`**
  - Get the schema/structure of a table
  - Example: `schema = get_lims_schema('Experiments')`

- **`count_lims_rows(table)`**
  - Count rows in a table
  - Example: `count = count_lims_rows('Genes')`

- **`show_table_info(table)`**
  - Display comprehensive information about a table
  - Example: `show_table_info('Measurements')`

## Tips for Using Notebooks

### Performance

1. **Use filters** to reduce data at the database level
2. **Select specific columns** you need rather than all columns
3. **Use limits** when exploring large tables
4. **Cache results** in variables to avoid repeated queries

### Pandas Integration

```python
# Query data
df = query_lims('Samples')

# Use pandas for analysis
df.groupby('Experiment')['Name'].count()
df[df['Strain'].str.contains('ADP1')]
df.sort_values('Timestamp', ascending=False)
```

### Visualization

```python
import matplotlib.pyplot as plt
import seaborn as sns

# Get data
measurements = query_lims('Measurements')

# Plot
plt.figure(figsize=(10, 6))
sns.boxplot(data=measurements, x='Measurement_type', y='Value')
plt.xticks(rotation=45)
plt.show()
```

## Troubleshooting

### LIMS API Not Available

If you see "Warning: LIMS API not available", make sure:
1. The conda environment is activated: `source activate.sh`
2. The LIMS database has been synced: `./lims.sh sync`
3. You're running from the project root directory

### Import Errors

If you get import errors:
1. Restart the Jupyter kernel (Kernel → Restart)
2. Make sure you're using the correct environment
3. Run `%run util_simple.py` in the first cell

### Database Empty

If queries return no results:
1. Check if the database has been synced: `./lims.sh list --count`
2. Run a manual sync: `./lims.sh sync`
3. Make sure Google Sheets credentials are configured

## Creating New Notebooks

When creating new notebooks in this directory:

1. Start with the setup cell:
```python
%run util_simple.py
import pandas as pd
import matplotlib.pyplot as plt
```

2. Use the helper functions for easy data access
3. Document your analysis with markdown cells
4. Save visualizations for reports

## Examples of Common Queries

```python
# Get all experiments
experiments = query_lims('Experiments')

# Get samples from a specific experiment
samples = query_lims('Samples', filters={'Experiment': 'ALE1b'})

# Search for strains
adp1_strains = search_lims('Strains', 'Name', 'ADP1')

# Get recent measurements
recent_measurements = query_lims(
    'Measurements',
    order_by='Timestamp',
    order_desc=True,
    limit=100
)

# Combine data from multiple tables
samples = query_lims('Samples')
measurements = query_lims('Measurements')
combined = samples.merge(measurements, left_on='Name', right_on='Sample')
```

## Further Help

- See the main README.md for LIMS CLI commands
- See SERVICE_ACCOUNT_SETUP.md for Google Sheets configuration
- See the LIMS API documentation in the code comments
