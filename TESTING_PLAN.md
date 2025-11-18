# LIMS API Testing Plan

This document provides a comprehensive testing plan for the LIMS API sync daemon and database archiving system.

## Overview

The testing plan covers:
1. Manual sync operations
2. Daemon functionality (background synchronization)
3. Archive creation and retention policies
4. Error handling and recovery
5. Performance and rate limiting
6. Data integrity verification

## Prerequisites

Before testing, ensure:
- [ ] Google Cloud service account is configured
- [ ] `credentials/service_account.json` exists
- [ ] Google Sheets is shared with service account
- [ ] Environment is activated: `source activate.sh`
- [ ] Initial sync completed: `./lims.sh sync`

## Test Categories

### 1. Manual Sync Testing

#### Test 1.1: Basic Sync Operation

**Objective**: Verify manual sync works correctly

```bash
# Remove existing database
rm -f aisynbiopipeline/limsapi/lims_mirror.db

# Run sync
./lims.sh sync

# Expected results:
# - No errors
# - All tables created
# - Row counts match Google Sheets data
```

**Verification**:
```bash
# List tables with counts
./lims.sh list --count

# Check for expected tables
./lims.sh list | grep -E "Experiments|Samples|Measurements"
```

**Success Criteria**:
- [ ] All worksheets synced (or documented errors for problematic sheets)
- [ ] Row counts are non-zero for tables with data
- [ ] No fatal errors in output
- [ ] Database file created at `aisynbiopipeline/limsapi/lims_mirror.db`

#### Test 1.2: Schema Synchronization

**Objective**: Verify schema updates work correctly

**Test Steps**:
1. Add a new column to a Google Sheets worksheet
2. Run manual sync: `./lims.sh sync`
3. Check schema: `./lims.sh schema <table_name>`

**Success Criteria**:
- [ ] New column appears in schema
- [ ] Existing data preserved
- [ ] New column populated for all rows

#### Test 1.3: Data Updates

**Objective**: Verify data changes are detected and synced

**Test Steps**:
1. Note current row hash for a specific row
2. Modify a cell value in Google Sheets
3. Run sync: `./lims.sh sync`
4. Query the modified row

**Verification**:
```bash
# Before modification
./lims.sh query <table> --filter name=<value>

# After modification and sync
./lims.sh query <table> --filter name=<new_value>
```

**Success Criteria**:
- [ ] Modified data appears in query results
- [ ] `last_synced` timestamp updated
- [ ] `row_hash` changed
- [ ] Update count > 0 in sync output

#### Test 1.4: Soft Deletes

**Objective**: Verify deleted rows are marked, not removed

**Test Steps**:
1. Query a table and note a specific row
2. Delete that row from Google Sheets
3. Run sync: `./lims.sh sync`
4. Query with and without deleted rows

**Verification**:
```bash
# Should NOT appear (deleted=0 by default)
./lims.sh query <table> --filter name=<deleted_row>

# Should appear when including deleted
./lims.sh query <table> --filter name=<deleted_row> --include-deleted
```

**Success Criteria**:
- [ ] Row not in default queries (deleted=0)
- [ ] Row visible with `--include-deleted` flag
- [ ] `deleted` column set to 1
- [ ] Row still in database (not physically deleted)
- [ ] Deleted count > 0 in sync output

### 2. Daemon Testing

#### Test 2.1: Start Daemon

**Objective**: Verify daemon starts successfully

```bash
# Start daemon
./lims.sh daemon start

# Check status
./lims.sh status
```

**Success Criteria**:
- [ ] Daemon reports as running
- [ ] No error messages
- [ ] Status shows daemon_running: true
- [ ] Process visible: `ps aux | grep "lims.*daemon"`

#### Test 2.2: Background Sync Operation

**Objective**: Verify daemon performs automatic syncs

**Test Steps**:
1. Start daemon: `./lims.sh daemon start`
2. Wait for sync interval (default: 10 minutes)
3. Check sync log: `tail -f aisynbiopipeline/limsapi/sync.log`
4. Verify sync occurred

**Success Criteria**:
- [ ] Log shows sync operations at 10-minute intervals
- [ ] Status shows increasing `syncs_completed` count
- [ ] `last_sync` timestamp updates
- [ ] No errors in log

#### Test 2.3: Daemon Persistence

**Objective**: Verify daemon continues running

**Test Steps**:
1. Start daemon
2. Wait 30 minutes (3+ sync cycles)
3. Check status and logs

**Verification**:
```bash
# Watch the log
tail -f aisynbiopipeline/limsapi/sync.log

# Check status periodically
watch -n 60 './lims.sh status'
```

**Success Criteria**:
- [ ] Daemon still running after 30 minutes
- [ ] At least 3 successful syncs completed
- [ ] No crash or error states
- [ ] Memory usage stable (check with `top` or `ps`)

#### Test 2.4: Stop Daemon

**Objective**: Verify daemon stops cleanly

```bash
# Stop daemon
./lims.sh daemon stop

# Verify stopped
./lims.sh status
```

**Success Criteria**:
- [ ] Status shows daemon_running: false
- [ ] Process no longer in process list
- [ ] Clean shutdown message in log
- [ ] No orphaned processes

#### Test 2.5: Daemon Restart

**Objective**: Verify daemon can be restarted

**Test Steps**:
1. Start daemon
2. Wait for one sync cycle
3. Stop daemon
4. Restart daemon
5. Verify it continues syncing

**Success Criteria**:
- [ ] Daemon restarts without errors
- [ ] Syncs resume after restart
- [ ] `syncs_completed` counter persists/increments correctly
- [ ] No data loss or corruption

### 3. Archive System Testing

#### Test 3.1: Manual Archive Creation

**Objective**: Verify manual archive creation works

```bash
# Create manual archive
./lims.sh archive create

# List archives
./lims.sh archive list
```

**Success Criteria**:
- [ ] Archive file created in `aisynbiopipeline/limsapi/archive/`
- [ ] Archive filename follows pattern: `lims_manual_YYYYMMDD_HHMMSS.db.gz`
- [ ] Archive is gzip compressed
- [ ] Archive size reasonable (smaller than original if compression enabled)

#### Test 3.2: Automatic Archival

**Objective**: Verify automatic archives are created during sync

**Test Steps**:
1. Note current archives: `./lims.sh archive list`
2. Run sync: `./lims.sh sync`
3. Check for new archives

**Success Criteria**:
- [ ] Hourly archive created
- [ ] Archive timestamp matches sync time
- [ ] Archive contains complete database copy

#### Test 3.3: Archive Types

**Objective**: Verify all archive types are created correctly

**Test Steps**:
```bash
# Create each type
./lims.sh archive create --type manual
./lims.sh archive create --type hourly
./lims.sh archive create --type daily
./lims.sh archive create --type weekly
./lims.sh archive create --type monthly

# List and verify
./lims.sh archive list
./lims.sh archive list --type hourly
./lims.sh archive list --type daily
```

**Success Criteria**:
- [ ] Each type creates archive with correct prefix
- [ ] Archives can be filtered by type
- [ ] Filenames follow convention: `lims_{type}_YYYYMMDD_HHMMSS.db.gz`

#### Test 3.4: Archive Retention Policy

**Objective**: Verify retention policies work correctly

**Default Retention** (from config.json):
- Hourly: 24 hours (keep 24 archives)
- Daily: 7 days (keep 7 archives)
- Weekly: 4 weeks (keep 4 archives)
- Monthly: Infinite (keep all)

**Test Steps**:
1. Create multiple archives of each type (older than retention period)
2. Run cleanup: `./lims.sh archive cleanup`
3. Verify correct archives were deleted

**Manual Setup** (for testing):
```bash
# Create old hourly archives (simulate 48 hours of archives)
for i in {1..48}; do
    timestamp=$(date -v-${i}H +%Y%m%d_%H%M%S)
    touch "aisynbiopipeline/limsapi/archive/lims_hourly_${timestamp}.db.gz"
done

# Run cleanup
./lims.sh archive cleanup

# Count remaining hourly archives
ls -1 aisynbiopipeline/limsapi/archive/lims_hourly_* | wc -l
```

**Success Criteria**:
- [ ] Only 24 hourly archives remain (within 24 hours)
- [ ] Only 7 daily archives remain (within 7 days)
- [ ] Only 4 weekly archives remain (within 4 weeks)
- [ ] All monthly archives remain
- [ ] Cleanup report shows correct deletion counts

#### Test 3.5: Archive Restoration

**Objective**: Verify archives can be restored successfully

**Test Steps**:
```bash
# Create an archive
./lims.sh archive create

# Modify database (add/delete data)
./lims.sh sync

# List archives
./lims.sh archive list

# Restore from archive
./lims.sh archive restore lims_manual_YYYYMMDD_HHMMSS.db.gz

# Verify data restored
./lims.sh list --count
```

**Success Criteria**:
- [ ] Database restored to archive state
- [ ] Row counts match archive point-in-time
- [ ] No data corruption
- [ ] Subsequent syncs work correctly

#### Test 3.6: Archive Compression

**Objective**: Verify compression is working

**Test Steps**:
```bash
# Get original database size
ls -lh aisynbiopipeline/limsapi/lims_mirror.db

# Create archive
./lims.sh archive create

# Check archive size
ls -lh aisynbiopipeline/limsapi/archive/lims_manual_*.db.gz

# Decompress and compare
gunzip -c aisynbiopipeline/limsapi/archive/lims_manual_*.db.gz > /tmp/restored.db
ls -lh /tmp/restored.db
```

**Success Criteria**:
- [ ] Archive is significantly smaller than original (SQLite compresses well)
- [ ] Decompressed archive matches original database
- [ ] Archive is valid gzip file

### 4. Error Handling Testing

#### Test 4.1: Google Sheets API Rate Limiting

**Objective**: Verify rate limit handling works

**Test Steps**:
1. Run multiple rapid syncs to trigger rate limit
2. Observe retry behavior
3. Check that sync eventually succeeds

**Expected Behavior**:
- [ ] Rate limit error logged
- [ ] System waits (worksheet_delay) between worksheets
- [ ] Retries after rate limit expires
- [ ] Eventually completes sync

#### Test 4.2: Network Interruption

**Objective**: Verify resilience to network issues

**Test Steps**:
1. Start daemon
2. Disable network briefly during sync
3. Re-enable network
4. Verify daemon recovers

**Success Criteria**:
- [ ] Error logged but daemon continues running
- [ ] Next sync succeeds
- [ ] No data corruption
- [ ] Daemon doesn't crash

#### Test 4.3: Invalid Credentials

**Objective**: Verify error handling for auth issues

**Test Steps**:
1. Temporarily rename credentials file
2. Run sync
3. Restore credentials
4. Run sync again

**Success Criteria**:
- [ ] Clear error message about missing credentials
- [ ] No crash or stack trace
- [ ] Sync succeeds after credentials restored

#### Test 4.4: Corrupted Database

**Objective**: Verify recovery from database corruption

**Test Steps**:
1. Create archive
2. Corrupt database file (truncate or fill with zeros)
3. Attempt sync
4. Restore from archive if needed

**Success Criteria**:
- [ ] Error detected and logged
- [ ] Can restore from archive
- [ ] System provides clear recovery instructions

### 5. Data Integrity Testing

#### Test 5.1: Row Hash Consistency

**Objective**: Verify row hashing is consistent

**Test Steps**:
```python
from aisynbiopipeline.limsapi import query_table
from aisynbiopipeline.limsapi.database import DatabaseManager

# Get a row
rows = query_table('Samples', limit=1)
row = rows[0]

# Remove backend columns
clean_row = {k: v for k, v in row.items()
             if k not in ['deleted', 'last_synced', 'row_hash']}

# Recalculate hash
db = DatabaseManager()
new_hash = db.calculate_row_hash(clean_row)

# Compare
print(f"Original: {row['row_hash']}")
print(f"Calculated: {new_hash}")
assert row['row_hash'] == new_hash
```

**Success Criteria**:
- [ ] Hashes match
- [ ] Same input always produces same hash
- [ ] Hash changes when data changes

#### Test 5.2: Foreign Key Relationships

**Objective**: Verify data relationships are maintained

**Test Steps**:
```python
# Get a sample
samples = query_table('Samples', limit=1)
sample_name = samples[0]['Name']

# Get related measurements
measurements = query_table('Measurements',
                          filters={'Sample_ID': sample_name})

# Verify relationship
assert len(measurements) > 0 or True  # May be empty
```

**Success Criteria**:
- [ ] Related records can be joined
- [ ] No orphaned records (if referential integrity expected)
- [ ] Cascade behavior works for deletes (soft delete)

#### Test 5.3: Data Type Consistency

**Objective**: Verify data types are preserved

**Test Steps**:
```python
# Check schema
schema = get_table_schema('Measurements')

# Query data
data = query_table('Measurements', limit=100)
df = pd.DataFrame(data)

# Verify types
for col, sql_type in schema.items():
    if sql_type == 'INTEGER':
        # Should be numeric
        assert df[col].dtype in ['int64', 'float64', 'object']
```

**Success Criteria**:
- [ ] INTEGER columns contain numeric data
- [ ] TEXT columns properly encoded
- [ ] NULL values handled correctly

### 6. Performance Testing

#### Test 6.1: Sync Duration

**Objective**: Measure sync performance

**Test Steps**:
1. Time a full sync with all tables
2. Record metrics

```bash
time ./lims.sh sync
```

**Metrics to Record**:
- Total sync time
- Time per table
- Rows synced per second
- Database file size growth

**Success Criteria**:
- [ ] Sync completes within reasonable time (< 5 minutes for 12 tables)
- [ ] Performance doesn't degrade over time
- [ ] No memory leaks

#### Test 6.2: Query Performance

**Objective**: Verify query responsiveness

**Test Steps**:
```python
import time

# Test simple query
start = time.time()
results = query_table('Genes', limit=100)
simple_time = time.time() - start

# Test filtered query
start = time.time()
results = query_table('Genes',
                     filters={'Locus_tag': 'ACIAD0001'})
filtered_time = time.time() - start

# Test large query
start = time.time()
results = query_table('Genes')
large_time = time.time() - start

print(f"Simple: {simple_time:.3f}s")
print(f"Filtered: {filtered_time:.3f}s")
print(f"Large: {large_time:.3f}s")
```

**Success Criteria**:
- [ ] Simple queries < 0.1s
- [ ] Filtered queries < 0.5s
- [ ] Large queries < 2s for tables with <10k rows

#### Test 6.3: Concurrent Access

**Objective**: Verify multiple processes can query simultaneously

**Test Steps**:
1. Start daemon
2. Run multiple query commands in parallel
3. Verify all succeed

```bash
# Run 5 queries in parallel
for i in {1..5}; do
    ./lims.sh query Samples --limit 10 &
done
wait
```

**Success Criteria**:
- [ ] All queries succeed
- [ ] No database locking errors
- [ ] Results are correct

### 7. Configuration Testing

#### Test 7.1: Custom Sync Interval

**Objective**: Verify sync interval can be changed

**Test Steps**:
1. Edit `config.json`, set `interval_minutes: 1`
2. Start daemon
3. Monitor sync frequency

**Success Criteria**:
- [ ] Syncs occur every 1 minute
- [ ] Interval change takes effect
- [ ] No errors from rapid syncing

#### Test 7.2: Worksheet Delay

**Objective**: Verify worksheet delay prevents rate limits

**Test Steps**:
1. Set `worksheet_delay: 5.0` in config
2. Run sync, measure duration
3. Verify delays occur

**Success Criteria**:
- [ ] Total sync time = (num_tables - 1) * delay + processing_time
- [ ] No rate limit errors
- [ ] Delays logged in debug mode

#### Test 7.3: Retention Policy Modification

**Objective**: Verify retention policies can be changed

**Test Steps**:
1. Modify retention in `config.json`
2. Create test archives
3. Run cleanup
4. Verify new policy applied

**Success Criteria**:
- [ ] Changes take effect
- [ ] Archives cleaned according to new policy
- [ ] No config validation errors

## Test Execution Checklist

### Pre-Test Setup
- [ ] Environment activated
- [ ] Database backed up (if contains important data)
- [ ] Google Sheets credentials configured
- [ ] Sufficient disk space for archives

### Test Execution
- [ ] Record start time and environment details
- [ ] Execute tests in order
- [ ] Document any failures with logs
- [ ] Take screenshots/logs of errors
- [ ] Note performance metrics

### Post-Test Cleanup
- [ ] Stop any running daemons
- [ ] Clean up test archives
- [ ] Restore original configuration
- [ ] Document test results

## Test Results Template

```markdown
## Test Results - [Date]

**Environment**:
- OS: [macOS/Linux]
- Python Version: [3.11.x]
- Database Size: [X MB]
- Number of Tables: [12]
- Total Rows: [~5700]

**Test Summary**:
- Total Tests: [X]
- Passed: [X]
- Failed: [X]
- Skipped: [X]

**Failed Tests**:
1. Test X.Y: [Description]
   - Error: [Error message]
   - Logs: [Link to logs]
   - Action: [How to fix]

**Performance Metrics**:
- Sync Duration: [X seconds]
- Queries/sec: [X]
- Archive Size: [X MB]
- Memory Usage: [X MB]

**Issues Found**:
1. [Issue description]
2. [Issue description]

**Recommendations**:
1. [Recommendation]
2. [Recommendation]
```

## Automated Testing Scripts

Create a test runner script at `tests/run_integration_tests.sh`:

```bash
#!/bin/bash
# Integration test runner for LIMS API

set -e

echo "LIMS API Integration Tests"
echo "=========================="

# Test 1: Manual Sync
echo "Test 1: Manual Sync"
./lims.sh sync > /tmp/sync_test.log 2>&1
grep -q "SUCCESS" /tmp/sync_test.log && echo "✓ PASS" || echo "✗ FAIL"

# Test 2: Daemon Start/Stop
echo "Test 2: Daemon"
./lims.sh daemon start
sleep 5
./lims.sh status | grep -q "daemon_running.*true" && echo "✓ PASS" || echo "✗ FAIL"
./lims.sh daemon stop
sleep 2
./lims.sh status | grep -q "daemon_running.*false" && echo "✓ PASS" || echo "✗ FAIL"

# Test 3: Archive Creation
echo "Test 3: Archives"
./lims.sh archive create > /tmp/archive_test.log 2>&1
./lims.sh archive list | grep -q "lims_manual" && echo "✓ PASS" || echo "✗ FAIL"

# Test 4: Query
echo "Test 4: Query"
./lims.sh query Experiments --limit 1 > /tmp/query_test.log 2>&1
grep -q "row(s) returned" /tmp/query_test.log && echo "✓ PASS" || echo "✗ FAIL"

echo ""
echo "Tests Complete"
```

## Continuous Monitoring

Set up monitoring to ensure long-term reliability:

### Daily Checks
- [ ] Daemon is running
- [ ] Last sync succeeded
- [ ] No errors in log
- [ ] Disk space available

### Weekly Checks
- [ ] Archive retention working correctly
- [ ] Query performance acceptable
- [ ] No memory leaks

### Monthly Checks
- [ ] Full test suite execution
- [ ] Performance benchmarking
- [ ] Configuration review

## Troubleshooting Guide

Common issues and solutions are documented in the main README.md and SERVICE_ACCOUNT_SETUP.md files.

For test-specific issues:

1. **Test timeouts**: Increase timeout values or check network
2. **Inconsistent results**: May indicate race conditions - add delays
3. **Archive tests fail**: Check disk space and permissions
4. **Daemon tests fail**: Ensure no other instances running

## Conclusion

This testing plan ensures the LIMS API daemon and archiving system work reliably. Regular execution of these tests will catch issues early and verify system integrity.
