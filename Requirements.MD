Act as an expert Data Architect. I need a fully functional, production-ready Python prototype of a "Shift-Left" Data Quality (DQ) Framework built using the Great Expectations library. This will be used for a live demo to senior leadership.

Please build the prototype around a banking use case using two data structures: a Daily Transactions file and a Customer Profile file (which includes critical GRC fields like PAN/Aadhaar).

The framework must utilize Great Expectations to explicitly demonstrate three zones of defense across all 6 core DQ dimensions:
1. Ingestion Zone (Circuit Breaker): 
   - Timeliness Check: Expect column values to be within an operational date range.
   - Validity Check: Expect transaction amounts to be positive numeric values type.
   - Completeness Check: Expect highly critical columns (like PAN/Aadhaar) to not be null. If a CRITICAL expectation fails, programmatically intercept the validation result to trip a "circuit breaker" and halt the pipeline.
2. Processing Zone (Transformation & Enrichment): 
   - Uniqueness Check: Expect Transaction_IDs to be completely unique to prevent double-counting.
   - Consistency Check: Expect Customer_IDs in the transaction data to match the values in the Customer Master table (foreign key/set validation).
3. Reporting Zone (Aggregate Analytics): 
   - Accuracy Check: Run a reconciliation validation ensuring the sum of processed transactions matches the expected ledger target.
   - Anomaly Detection: Expect the daily transaction volume to fall within a historically acceptable min/max threshold.

Technical Architecture Requirements for the Code:
- Great Expectations Core Implementation: Create the Data Context programmatically, define the Expectation Suites for each zone, and run them using Checkpoints.
- Declarative Rules & Criticality: Show how expectations are configured as code. Differentiate between CRITICAL rules (stops the pipeline) and WARNING rules (logs the issue but allows the pipeline to finish).
- Centralized Metadata Logging: Capture the validation_result dict returned by Great Expectations. Parse it to print a clean "Audit Trail" summary at the end of the script showing: Zone, Dimension, Expectation Type, Status (Pass/Fail), and Criticality.
- Clean Console Output: Use formatted print statements with emojis (✅, ❌, ⚠️) so the audience can easily follow the execution flow.

Provide the complete, end-to-end runnable Python script. Include a small block of mock data generation using Pandas inside the script itself, along with two execution scenarios:
Scenario A: A healthy dataset that passes the Expectation Suites cleanly across all zones.
Scenario B: A corrupted dataset that fails a critical completeness expectation (missing PAN numbers), showing how the code catches the failure and triggers the circuit breaker.